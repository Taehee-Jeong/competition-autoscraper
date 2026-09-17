# -*- coding: utf-8 -*-
"""AlphaEvolve 스타일 규칙 진화 엔진.

원리 (DeepMind AlphaEvolve의 축소판):
  후보 생성 → 자동 평가 → 상위 선택 → LLM/휴리스틱 변이 → 반복

진화 대상은 안전을 위해 '검증 가능한 설정(JSON)'으로 제한:
  - 필터 정규식 목록 (재학생/팀 판정)
  - 학부 분류 키워드 사전
임의 코드는 절대 생성·실행하지 않는다. 모든 후보 정규식은
컴파일 검증 + 길이 제한을 통과해야 개체군에 들어간다.

평가셋: data/평가셋.jsonl (한 줄 = 한 대회, 정답 라벨 포함)
  {"body": "...", "target": "...", "student_ok": true, "team_ok": true,
   "school": "School of Engineering"}
사람이 엑셀에서 '확정'으로 검수한 대회는 harvest로 평가셋에 자동 축적된다.

실행:  python evolve.py            (세대 8, 개체 6 기본)
       GENERATIONS=15 POPULATION=8 python evolve.py
결과:  data/rules.json  ← main.py가 다음 실행부터 자동 적용
"""
import os
import re
import json
import copy
import random
import logging
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import filters, classify

logging.basicConfig(level=logging.INFO, format="%(asctime)s evolve %(message)s")
log = logging.getLogger("evolve")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GOLDEN = os.path.join(DATA, "평가셋.jsonl")
RULES = os.path.join(DATA, "rules.json")
EVOLOG = os.path.join(DATA, "evolve_log.json")

# 상한은 filters/classify가 갖고 있는 것을 그대로 쓴다 (검증 기준이 갈리면 안 됨)
MAX_PATTERNS_PER_LIST = filters.MAX_PATTERNS_PER_LIST
MAX_PATTERN_LEN = filters.MAX_PATTERN_LEN


# ------------------------------------------------------------------ 평가
def load_golden() -> list[dict]:
    rows = []
    if os.path.exists(GOLDEN):
        for line in open(GOLDEN, encoding="utf-8"):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _judge_to_score(pred: str, truth: bool) -> float:
    """통과/탈락/확인필요 vs 정답 → 점수. 확인필요는 부분 점수(0.4)."""
    if pred == "확인필요":
        return 0.4
    return 1.0 if (pred == "통과") == truth else 0.0


def evaluate(cfg: dict, golden: list[dict]) -> float:
    """후보 규칙 1개의 적합도 = 평가셋 평균 점수 (0~1)."""
    filters.set_rules(cfg["filters"])
    classify.set_school_keywords(cfg["schools"])
    if not golden:
        return 0.0
    total = 0.0
    for g in golden:
        item = {"target": g.get("target", ""), "body": g.get("body", ""),
                "lang": g.get("lang", "ko"), "title": g.get("title", ""),
                "field": g.get("field", "")}
        s = _judge_to_score(filters.check_student(item), g.get("student_ok", True))
        t = _judge_to_score(filters.check_team(item), g.get("team_ok", True))
        parts = [s, t]
        if g.get("school"):
            parts.append(1.0 if classify.classify_school(item) == g["school"] else 0.0)
        total += sum(parts) / len(parts)
    return total / len(golden)


def misclassified(cfg: dict, golden: list[dict], k: int = 5) -> list[dict]:
    filters.set_rules(cfg["filters"])
    classify.set_school_keywords(cfg["schools"])
    bad = []
    for g in golden:
        item = {"target": g.get("target", ""), "body": g.get("body", ""),
                "lang": g.get("lang", "ko"), "title": g.get("title", ""),
                "field": g.get("field", "")}
        wrong = []
        if _judge_to_score(filters.check_student(item), g.get("student_ok", True)) < 1:
            wrong.append("student")
        if _judge_to_score(filters.check_team(item), g.get("team_ok", True)) < 1:
            wrong.append("team")
        if g.get("school") and classify.classify_school(item) != g["school"]:
            wrong.append("school")
        if wrong:
            bad.append({**g, "_wrong": wrong})
    random.shuffle(bad)
    return bad[:k]


# ------------------------------------------------------------------ 검증 (안전장치)
def valid_config(cfg: dict, base: dict) -> bool:
    """LLM/변이가 만든 후보를 개체군에 넣기 전 검증."""
    try:
        f, s = cfg["filters"], cfg["schools"]
        if set(f.keys()) != set(base["filters"].keys()):
            return False
        if set(s.keys()) != set(base["schools"].keys()):
            return False
        filters.validate_rules(f)  # 컴파일·길이·개수 검증 (실패 시 ValueError)
        for kws in s.values():
            if not isinstance(kws, list) or len(kws) > classify.MAX_KEYWORDS_PER_SCHOOL:
                return False
            if not all(isinstance(k, str) and 0 < len(k) <= 40 for k in kws):
                return False
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ 변이
MUTATE_PROMPT = """당신은 규칙 최적화 엔진입니다. 아래는 공모전 판정용 규칙(JSON)과,
이 규칙이 틀린 사례들입니다. 틀린 사례를 맞히도록 규칙을 소폭 수정하세요.

수정 원칙:
- 정규식/키워드의 추가·삭제·수정만 허용. 구조(키 이름)는 유지.
- 각 정규식은 {maxlen}자 이하, 리스트당 {maxn}개 이하.
- 기존에 잘 맞던 패턴을 함부로 지우지 말 것 (소폭 변이).
JSON 객체 하나만 출력하세요. 설명·마크다운 금지.

현재 규칙:
{cfg}

틀린 사례 (필드 _wrong = 틀린 판정 종류):
{examples}
"""


def mutate_llm(cfg: dict, bad: list[dict]) -> dict | None:
    """Ollama에게 규칙 수정을 제안받는다. 서버 없으면 None."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    import requests
    try:
        r = requests.post(f"{host}/api/chat", timeout=240, json={
            "model": model, "stream": False, "format": "json",
            "options": {"temperature": 0.7, "num_ctx": 8192},
            "messages": [{"role": "user", "content": MUTATE_PROMPT.format(
                maxlen=MAX_PATTERN_LEN, maxn=MAX_PATTERNS_PER_LIST,
                cfg=json.dumps(cfg, ensure_ascii=False),
                examples=json.dumps(bad, ensure_ascii=False)[:3000])}],
        })
        r.raise_for_status()
        return json.loads((r.json().get("message") or {}).get("content", ""))
    except Exception as e:
        log.info("LLM 변이 불가(%s) — 휴리스틱 변이 사용", e.__class__.__name__)
        return None


_TOKEN = re.compile(r"[가-힣]{2,8}|[A-Za-z]{3,15}")


def mutate_heuristic(cfg: dict, bad: list[dict]) -> dict:
    """Ollama 없이도 도는 변이: 오답 사례의 토큰을 규칙에 추가/삭제."""
    new = copy.deepcopy(cfg)
    if bad and random.random() < 0.8:
        g = random.choice(bad)
        text = f"{g.get('target','')} {g.get('body','')}"
        tokens = [t for t in _TOKEN.findall(text)]
        if tokens:
            tok = re.escape(random.choice(tokens))
            if "school" in g["_wrong"] and g.get("school"):
                lst = new["schools"][g["school"]]
                if tok not in lst and len(lst) < 40:
                    lst.append(random.choice(tokens))
            elif "student" in g["_wrong"]:
                key = "student_pos" if g.get("student_ok", True) else "student_neg"
                lst = new["filters"][key]
                if tok not in lst and len(lst) < MAX_PATTERNS_PER_LIST:
                    lst.append(tok)
            elif "team" in g["_wrong"]:
                key = "team_pos" if g.get("team_ok", True) else "team_neg"
                lst = new["filters"][key]
                if tok not in lst and len(lst) < MAX_PATTERNS_PER_LIST:
                    lst.append(tok)
    else:  # 가끔은 패턴 하나 제거 (과적합 방지)
        key = random.choice(list(new["filters"].keys()))
        if len(new["filters"][key]) > 2:
            new["filters"][key].pop(random.randrange(len(new["filters"][key])))
    return new


# ------------------------------------------------------------------ 진화 루프
def base_config() -> dict:
    return {"filters": filters.get_rules(),
            "schools": {k: list(v) for k, v in classify.SCHOOL_KEYWORDS.items()}}


def evolve():
    golden = load_golden()
    if len(golden) < 4:
        log.warning("평가셋이 %d건뿐입니다. data/평가셋.jsonl에 검수 결과를 "
                    "쌓을수록 진화 품질이 올라갑니다.", len(golden))
    if not golden:
        log.error("평가셋이 없어 진화를 건너뜁니다.")
        return

    gens = int(os.environ.get("GENERATIONS", "8"))
    pop_n = int(os.environ.get("POPULATION", "6"))
    base = base_config()

    # 저장된 챔피언이 있으면 이어서 진화
    champion = base
    if os.path.exists(RULES):
        try:
            saved = json.load(open(RULES, encoding="utf-8"))["config"]
            if valid_config(saved, base):
                champion = saved
        except Exception:
            pass

    population = [copy.deepcopy(champion)]
    while len(population) < pop_n:
        population.append(mutate_heuristic(champion, misclassified(champion, golden)))

    history = []
    for gen in range(1, gens + 1):
        scored = sorted(((evaluate(c, golden), c) for c in population),
                        key=lambda x: -x[0])
        best_score, best = scored[0]
        history.append({"gen": gen, "best": round(best_score, 4),
                        "scores": [round(s, 4) for s, _ in scored]})
        log.info("세대 %d/%d  최고 %.3f  개체 %s", gen, gens, best_score,
                 [f"{s:.2f}" for s, _ in scored])
        if best_score >= 0.999:
            champion = best
            break
        # 선택: 상위 2 생존 → 변이로 나머지 채움
        parents = [c for _, c in scored[:2]]
        nxt = [copy.deepcopy(p) for p in parents]
        while len(nxt) < pop_n:
            parent = random.choice(parents)
            bad = misclassified(parent, golden)
            child = None
            if random.random() < 0.5:
                child = mutate_llm(parent, bad)
            if not child or not valid_config(child, base):
                child = mutate_heuristic(parent, bad)
            if valid_config(child, base):
                nxt.append(child)
        population = nxt
        champion = best

    final = evaluate(champion, golden)
    json.dump({"score": round(final, 4), "generations": len(history),
               "config": champion}, open(RULES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(history, open(EVOLOG, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log.info("진화 완료: 최종 점수 %.3f → %s 저장", final, RULES)


# ------------------------------------------------------------------ 평가셋 수확
def harvest_from_xlsx():
    """검수 완료('확정' 표시) 행을 평가셋에 긍정 사례로 축적."""
    from openpyxl import load_workbook
    path = os.path.join(DATA, "후보_컴피티션_목록.xlsx")
    if not os.path.exists(path):
        return 0
    seen = {json.loads(l)["title"] for l in open(GOLDEN, encoding="utf-8")} \
        if os.path.exists(GOLDEN) else set()
    ws = load_workbook(path, read_only=True).active
    added = 0
    with open(GOLDEN, "a", encoding="utf-8") as f:
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 13:
                continue
            title, school, status = row[2], row[1], str(row[12] or "")
            if "확정" not in status or not title or title in seen:
                continue
            f.write(json.dumps({
                "title": title, "field": row[4] or "", "target": row[8] or "",
                "body": f"{row[4] or ''} {row[6] or ''} {row[7] or ''} {row[8] or ''}",
                "student_ok": True, "team_ok": True,
                "school": school if school and school != "미분류" else None,
            }, ensure_ascii=False) + "\n")
            seen.add(title)
            added += 1
    log.info("검수 결과 %d건을 평가셋에 추가", added)
    return added


if __name__ == "__main__":
    harvest_from_xlsx()
    evolve()
