# -*- coding: utf-8 -*-
"""웹에서 main.py를 돌리고 로그를 보여준다.

수집은 26분쯤 걸리므로 요청을 받은 자리에서 기다리지 않는다.
백그라운드로 띄우고 로그 파일을 남긴 뒤, 끝나면 DB에 결과를 적는다.
동시에 두 번 돌면 같은 엑셀에 각자 쓰게 되므로 한 번에 하나만 허용한다.
"""
import os
import re
import sys
import fcntl
import threading
import subprocess
from datetime import datetime

from . import db

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE, "data", "runs")
PYTHON = os.environ.get("SCRAPER_PYTHON", sys.executable)
# cron(run.sh)이 쓰는 것과 같은 락. 이걸 공유해야 웹 실행과 주간 cron이 겹치지 않는다.
LOCK_PATH = "/tmp/competition-scraper.lock"


def active_run():
    """정말로 돌고 있는 실행만 돌려준다.

    gunicorn이 재시작되면 진행을 지켜보던 스레드가 사라져 runs 행이 'running'에
    영원히 묶인다. 그러면 [지금 수집하기]와 AI 검수가 영구히 막힌다.
    락을 잡을 수 있다는 건 아무도 안 돌고 있다는 뜻이므로, 그때 남은 행을 정리한다.
    """
    row = db.running_run()
    if row is None:
        return None
    fd = _acquire_lock()
    if fd is None:
        return row          # 락이 잡혀 있다 = 진짜로 돌고 있다
    os.close(fd)
    db.finish_run(row["id"], "failed")
    return db.running_run()


def _acquire_lock():
    """수집을 한 번에 하나만 돌게 한다. 못 잡으면 None.

    DB의 running 확인만으로는 부족하다 — gunicorn 스레드 8개가 동시에 그 검사를
    통과해 main.py 8개를 띄우고, 마지막에 저장하는 프로세스가 나머지가 모은 걸
    통째로 덮어써 조용히 날린다 (실측: 80건 중 60건 유실).
    """
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd

# 실행이 끝난 뒤 로그에서 건수를 뽑아낸다
PATTERNS = {"collected": r"수집 합계: (\d+)건",
            "passed": r"필터 통과: (\d+)건",
            "added": r"신규 추가 (\d+)건"}


def _parse_counts(log_path: str) -> dict:
    try:
        text = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    out = {}
    for key, pat in PATTERNS.items():
        m = re.findall(pat, text)
        out[key] = int(m[-1]) if m else None
    return out


def _watch(proc: subprocess.Popen, run_id: int, log_path: str, lock_fd: int):
    try:
        code = proc.wait()
        counts = _parse_counts(log_path)
        db.finish_run(run_id, "done" if code == 0 else "failed", **counts)
    finally:
        os.close(lock_fd)   # 여기서만 다음 실행이 가능해진다


def start(sources: str = "", max_details: str = "", pages: str = "",
          use_llm: bool = True) -> int | None:
    """수집을 백그라운드로 시작. 이미 돌고 있으면 None."""
    lock_fd = _acquire_lock()
    if lock_fd is None:
        return None
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"run_{stamp}.log")

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    if sources:
        env["SOURCES"] = sources
    if max_details:
        env["MAX_DETAILS"] = max_details
    if pages:
        env["PAGES"] = pages
    env["LLM_MAX_ITEMS"] = "500" if use_llm else "0"

    run_id = db.start_run(log_path)
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([PYTHON, "-u", "main.py"], cwd=BASE, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    threading.Thread(target=_watch, args=(proc, run_id, log_path, lock_fd),
                     daemon=True).start()
    return run_id


def start_aijudge(redo: bool = False) -> int | None:
    """AI 검수를 백그라운드로 시작. 수집이 돌고 있으면 None (GPU를 같이 쓴다)."""
    if active_run():
        return None
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"aijudge_{stamp}.log")
    run_id = db.start_run(log_path, kind="aijudge")

    def work():
        from . import aijudge
        with open(log_path, "w", encoding="utf-8") as f:
            def note(i, total, title, res):
                f.write(f"[{i}/{total}] {res['decision']:<5} "
                        f"({res['confidence']}) {title[:44]}\n")
                if res.get("rationale"):
                    f.write(f"        근거: {res['rationale'][:90]}\n")
                f.flush()
            try:
                f.write(f"AI 검수 시작 (모델 {aijudge.MODEL})\n")
                f.flush()
                t = aijudge.judge_all(redo=redo, progress=note)
                f.write(f"\n완료: 판정 {t['판정']}건 — 확정 {t['확정']} / "
                        f"기각 {t['기각']} / 판단보류 {t['판단보류']}\n")
                db.finish_run(run_id, "done", collected=t["판정"],
                              passed=t["확정"], added=t["기각"])
            except Exception as e:
                f.write(f"\n실패: {e}\n")
                db.finish_run(run_id, "failed")

    threading.Thread(target=work, daemon=True).start()
    return run_id


def tail(log_path: str, lines: int = 300) -> str:
    if not log_path or not os.path.exists(log_path):
        return "(로그 없음)"
    with open(log_path, encoding="utf-8", errors="replace") as f:
        return "".join(f.readlines()[-lines:])


def progress(log_path: str) -> str:
    """로그 마지막의 의미 있는 한 줄 — 목록 화면에 진행 상황으로 띄운다."""
    text = tail(log_path, 60)
    for line in reversed(text.splitlines()):
        if " INFO " in line:
            return line.split(" INFO ", 1)[1]
    return "시작하는 중"
