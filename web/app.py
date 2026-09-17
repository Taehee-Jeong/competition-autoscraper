# -*- coding: utf-8 -*-
"""공모전 후보 검수 웹 (내부용).

실행:  ./run_web.sh          → http://127.0.0.1:8000
환경변수:
  WEB_USER      기본 taehee
  WEB_PASSWORD  로그인 비밀번호 (반드시 지정. 없으면 기동 거부)
  WEB_SECRET    세션 서명 키 (없으면 매 기동마다 임의 생성 → 재시작 시 재로그인)
  WEB_DB        SQLite 경로 (기본 data/review.sqlite3)
"""
import os
import io
import sys
import time
import secrets
from difflib import SequenceMatcher
from functools import wraps

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, send_file, abort, jsonify)

from web import db, runner, scoring, dedupe

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER = os.environ.get("WEB_USER", "taehee")
PASSWORD = os.environ.get("WEB_PASSWORD")

if not PASSWORD:
    raise RuntimeError("WEB_PASSWORD 환경변수가 없습니다. run_web.sh / serve_web.sh로 실행하세요.")

app = Flask(__name__)
app.secret_key = os.environ.get("WEB_SECRET") or secrets.token_hex(32)
db.init()   # gunicorn으로 띄울 때도 스키마가 준비되도록 import 시점에 한 번


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (request.form.get("user", "") == USER
                and secrets.compare_digest(request.form.get("password", ""), PASSWORD)):
            session["user"] = USER
            return redirect(request.args.get("next") or url_for("index"))
        time.sleep(1)   # 망에 열어두므로 비밀번호 대입 시도를 느리게 만든다
        flash("아이디 또는 비밀번호가 맞지 않습니다.")
    return render_template("login.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/learn")
def learn():
    """크롤링 10일 학습 과정. 배우는 자료이므로 로그인 없이 연다."""
    from web.curriculum import DAYS
    return render_template("learn.html", days=DAYS)


# ------------------------------------------------------------------ 목록
@app.get("/")
@login_required
def index():
    f = {k: request.args.get(k, "") for k in ("status", "school", "source", "decision", "q")}
    sort = request.args.get("sort", "deadline")
    rows = db.list_candidates(sort=sort, **f)
    scored = [(r, *scoring.summary(r)) for r in rows]
    if sort == "score":
        scored.sort(key=lambda x: -x[1])
    elif sort == "score_low":
        scored.sort(key=lambda x: x[1])
    elif sort == "prize":
        scored.sort(key=lambda x: -db.prize_won(x[0]["prize"]))
    active = runner.active_run()
    return render_template(
        "list.html", rows=scored, f=f, sort=sort, threshold=db.AUTO_THRESHOLD, counts=db.counts(), ai=db.ai_counts(),
        schools=db.distinct("school"), sources=db.distinct("source"),
        statuses=db.distinct("auto_status"), days_left=db.days_left,
        sort_labels=db.SORT_LABELS, prize_won=db.prize_won,
        reasons=db.REJECT_REASONS,
        running=active, progress=runner.progress(active["log_path"]) if active else "",
        dupe_count=len(find_dupes()))


# ------------------------------------------------------------------ AI 검수
@app.post("/ai/judge")
@login_required
def ai_judge():
    rid = runner.start_aijudge(redo=request.form.get("redo") == "on")
    if rid:
        flash("AI가 미검수 건을 훑고 있습니다. 결과는 목록에 '제안'으로 표시됩니다.")
    else:
        flash("지금 수집이 돌고 있어 시작할 수 없습니다. 같은 GPU를 쓰기 때문입니다.")
    return redirect(url_for("runs") if rid else url_for("index"))


@app.post("/ai/apply")
@login_required
def ai_apply():
    n = db.apply_ai_reviews(only=request.form.get("only", ""),
                            min_confidence=request.form.get("min_confidence", ""))
    flash(f"AI 제안 {n}건을 적용했습니다. 담당자 칸에 'AI'로 남고, 규칙 학습에는 쓰지 않습니다."
          if n else "적용할 AI 제안이 없습니다.")
    return redirect(request.form.get("back") or url_for("index"))


@app.post("/bulk/confirm")
@login_required
def bulk_confirm():
    """점수가 기준 이상인 미검수 건을 한 번에 확정한다.

    사람이 690건을 하나씩 누를 수는 없으니 필요한 기능이지만, 판단 근거는
    남긴다 — 담당자 칸에 '자동(N점 이상)'으로, 출처는 'ai'로 표시돼
    나중에 어떤 건이 자동 처리됐는지 되짚을 수 있고 규칙 학습에는 안 쓰인다.
    """
    try:
        th = int(request.form.get("threshold", db.AUTO_THRESHOLD))
    except ValueError:
        flash("기준 점수는 숫자로 넣어주세요.")
        return redirect(url_for("index"))
    th = max(0, min(100, th))
    done = 0
    for r in db.list_candidates(decision="미검수"):
        if scoring.score(r)[0] >= th:
            db.set_review(r["id"], "확정", owner=f"자동({th}점↑)", source="ai")
            done += 1
    flash(f"{th}점 이상 {done}건을 확정했습니다. 담당자 칸에 '자동'으로 남아 있어 "
          f"나중에 되돌릴 수 있고, 규칙 학습에는 쓰지 않습니다."
          if done else f"{th}점 이상인 미검수 건이 없습니다.")
    return redirect(request.form.get("back") or url_for("index"))


@app.post("/review/<int:cid>")
@login_required
def review(cid):
    if not db.get(cid):
        abort(404)
    decision = request.form.get("decision", "")
    if decision == "취소":
        db.clear_review(cid)
    else:
        try:
            db.set_review(cid, decision, request.form.get("reason", ""),
                          request.form.get("owner", ""), request.form.get("note", ""))
        except ValueError as e:
            flash(str(e))
    return redirect(request.form.get("back") or url_for("index"))


@app.get("/c/<int:cid>")
@login_required
def detail(cid):
    row = db.get(cid)
    if not row:
        abort(404)
    return render_template("detail.html", c=row, reasons=db.REJECT_REASONS,
                           days_left=db.days_left(row["deadline"]),
                           back=request.args.get("back", url_for("index")))


# ------------------------------------------------------------------ 중복
def find_dupes(threshold: float = dedupe.DEFAULT_THRESHOLD) -> list[tuple]:
    return dedupe.pairs(threshold)


def _threshold() -> float:
    try:
        th = float(request.values.get("th", dedupe.DEFAULT_THRESHOLD))
    except ValueError:
        th = dedupe.DEFAULT_THRESHOLD
    return min(0.99, max(0.70, th))


@app.get("/dupes")
@login_required
def dupes():
    th = _threshold()
    groups = [(dedupe.keeper(g), g) for g in dedupe.clusters(th)]
    return render_template("dupes.html", groups=groups, th=th,
                           days_left=db.days_left, score=lambda r: scoring.score(r)[0])


@app.post("/merge/auto")
@login_required
def merge_auto():
    th = _threshold()
    merged, groups, notes = dedupe.auto_merge(th)
    flash(f"{groups}묶음에서 {merged}건을 합쳤습니다. 각 묶음에서 점수가 가장 높은 줄만 남겼고, "
          f"검수를 마친 줄은 건드리지 않았습니다. 되돌리려면 아래 '합친 것 되돌리기'를 누르세요."
          if merged else "합칠 만한 묶음이 없습니다.")
    return redirect(url_for("dupes", th=th))


@app.post("/merge/undo")
@login_required
def merge_undo():
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM merges").fetchone()[0]
        conn.execute("DELETE FROM merges")
    flash(f"합쳤던 {n}건을 되돌렸습니다. 목록에 다시 나타납니다.")
    return redirect(url_for("dupes"))


@app.post("/merge")
@login_required
def do_merge():
    try:
        db.merge(int(request.form["dup_id"]), int(request.form["keep_id"]))
        flash("합쳤습니다. 합쳐진 쪽은 목록과 엑셀에서 빠집니다.")
    except (ValueError, KeyError) as e:
        flash(f"합치기 실패: {e}")
    return redirect(url_for("dupes"))


# ------------------------------------------------------------------ 실행
@app.get("/runs")
@login_required
def runs():
    import main
    active = runner.active_run()
    groups = {}
    for key, (name, kind, note) in main.SOURCE_INFO.items():
        groups.setdefault(kind, []).append(
            {"key": key, "name": name, "note": note,
             "on": key in main.DEFAULT_SOURCES.split(",")})
    return render_template("runs.html", runs=db.recent_runs(), running=active,
                           groups=groups, log=runner.tail(active["log_path"]) if active else "")


@app.post("/runs/start")
@login_required
def start_run():
    import main
    picked = [s for s in request.form.getlist("source") if s in main.SOURCE_REGISTRY]
    if not picked:
        flash("소스를 하나 이상 골라주세요.")
        return redirect(url_for("runs"))
    md = request.form.get("max_details", "").strip()
    pg = request.form.get("pages", "").strip()
    for val, name in ((md, "소스당 건수"), (pg, "목록 페이지 수")):
        if val and not val.isdigit():
            flash(f"{name}는 숫자만 넣어주세요.")
            return redirect(url_for("runs"))
    rid = runner.start(sources=",".join(picked), max_details=md, pages=pg,
                       use_llm=request.form.get("use_llm") == "on")
    flash(f"{len(picked)}개 소스 수집을 시작했습니다. 아래에 진행 상황이 나옵니다."
          if rid else "이미 수집이 돌고 있습니다. 끝난 뒤에 다시 눌러주세요.")
    return redirect(url_for("runs"))


@app.get("/runs/<int:rid>/log")
@login_required
def run_log(rid):
    for r in db.recent_runs(200):
        if r["id"] == rid:
            return jsonify(status=r["status"], log=runner.tail(r["log_path"]))
    abort(404)


# ------------------------------------------------------------------ 내보내기
@app.get("/export.xlsx")
@login_required
def export_xlsx():
    from web.sync import export_xlsx as build
    buf = io.BytesIO()
    build(buf, only=request.args.get("only", ""))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="후보_컴피티션_목록.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/export/goldenset")
@login_required
def export_goldenset():
    path = os.path.join(BASE, "data", "평가셋_검수.jsonl")
    n = db.write_goldenset(path)
    flash(f"검수 결과 {n}건을 {os.path.basename(path)}로 내보냈습니다."
          if n else "아직 본문이 있는 확정·기각 건이 없습니다. 수집을 한 번 돌린 뒤 검수하세요.")
    return redirect(url_for("index"))


def main():
    """개발용 단독 실행. 상시 운영은 serve_web.sh(gunicorn)를 쓴다."""
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
