# -*- coding: utf-8 -*-
"""학부 분류 + (선택) Ollama 로컬 LLM 정밀 추출.

Ollama 서버(기본 http://localhost:11434)가 떠 있으면 로컬 모델이 본문을 읽고
팀 인원·참가비·일정·한 줄 소개·학부까지 구조화 추출한다.
서버가 없으면 키워드 규칙만으로 분류한다. API 키·비용 불필요.

환경변수:
  OLLAMA_HOST   기본 http://localhost:11434
  OLLAMA_MODEL  기본 qwen2.5:3b  (한국어 강화 모델: exaone3.5:2.4b 권장)
"""
import os
import json
import re
import logging

log = logging.getLogger("classify")

# 문서의 '분야/주제 예시' 기준 키워드 → 학부 매핑
SCHOOL_KEYWORDS = {
    "School of Business Management": [
        "창업", "비즈니스", "사업계획", "마케팅", "경영", "케이스", "금융", "브랜드",
        "startup", "business", "fintech", "marketing", "pitch"],
    "School of Engineering": [
        "SW", "소프트웨어", "앱", "해커톤", "프로그래밍", "AI", "인공지능",
        "로보틱스", "로봇", "공학", "캡스톤", "설계", "IT", "웹/모바일", "게임",
        "hackathon", "machine learning", "blockchain", "web3", "developer",
        "software", "robotics", "engineering", "coding", "app"],
    "School of Science": [
        "데이터", "통계", "분석", "바이오", "화학", "과학", "R&D", "연구"],
    "School of humanities and social Science": [
        "정책", "사회문제", "사회혁신", "에세이", "콘텐츠", "스토리텔링",
        "문학", "글", "기획", "논문", "수기"],
    "Academy of Interdisciplinary Studies": [
        "융합", "디자인씽킹", "ESG", "지속가능", "소셜임팩트", "환경", "탄소",
        "sustainability", "social impact", "climate", "for good"],
}


MAX_KEYWORDS_PER_SCHOOL = 40


def set_school_keywords(kw: dict):
    """진화 엔진이 만든 학부 키워드 사전으로 교체. 형식이 어긋나면 무시한다."""
    global SCHOOL_KEYWORDS
    if not isinstance(kw, dict) or set(kw.keys()) != set(SCHOOL_KEYWORDS.keys()):
        return
    for v in kw.values():
        if not isinstance(v, list) or len(v) > MAX_KEYWORDS_PER_SCHOOL:
            return
        if not all(isinstance(k, str) and 0 < len(k) <= 40 for k in v):
            return
    SCHOOL_KEYWORDS = {k: list(v) for k, v in kw.items()}


def _keyword_hit(kw: str, text: str) -> bool:
    """키워드가 텍스트에 나타나는가. 영문은 단어 경계를 지킨다.

    예전엔 소문자 부분일치라 'IT'가 compet-it-ion·dig-it-al에, 'AI'가
    sust-ai-nability에 걸려 영문 제목이 사실상 전부 공대로 분류됐다.
    한글은 조사·합성어 때문에 부분일치가 맞으므로 그대로 둔다.
    """
    if re.search(r"[가-힣]", kw):
        return kw in text
    # 앞뒤가 영숫자만 아니면 되므로 'startup경진대회', '웹/모바일/IT'는 그대로 잡힌다
    flags = 0 if (kw.isalpha() and kw.isupper()) else re.IGNORECASE  # 약어는 대소문자 구분
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(kw)}(?![A-Za-z0-9])",
                     text, flags) is not None


def classify_school(item: dict) -> str:
    text = f"{item.get('title','')} {item.get('field','')}"
    scores = {}
    for school, kws in SCHOOL_KEYWORDS.items():
        s = sum(1 for k in kws if _keyword_hit(k, text))
        if s:
            scores[school] = s
    return max(scores, key=scores.get) if scores else "미분류"


# ---------------------------------------------------------------- Claude API
# 주의: 항목 설명을 JSON '값 자리'에 넣으면 안 된다. 3B 모델은 값 자리의 문장을
# 채울 틀이 아니라 베낄 본보기로 취급해서, 설명문이나 예시를 그대로 답으로 돌려준다.
# (예시 '2~4인 / 개인 참가 불가'를 넣었더니 채워진 값의 68%가 그 문자열이었다.)
# 그래서 설명은 JSON 밖에 두고, 출력 틀은 빈 값만 남긴다.
EXTRACT_PROMPT = """다음은 공모전/경진대회 공고입니다. 본문에서 아래 항목을 찾아 JSON으로만 답하세요.

찾을 항목:
- team_size: 팀 구성 인원, 개인 참가 가능 여부
- eligibility: 참가 자격
- schedule: 예선·본선·발표 날짜
- fee: 참가비
- prize: 상금·혜택
- school: 다음 중 하나 — {schools}
- student_ok: 재학생 참가 가능하면 true, 불가하면 false
- team_ok: 팀 참가 가능하면 true, 불가하면 false

규칙:
- **본문에 적혀 있는 것만 쓰세요.** 본문에 없으면 문자열은 "확인필요", student_ok·team_ok는 null.
- 흔한 값이라고 짐작하지 마세요. 참가비가 안 적혀 있으면 "무료"가 아니라 "확인필요"입니다.
- student_ok나 team_ok를 false로 쓰면 이 대회는 목록에서 삭제됩니다. 확신이 없으면 null.
- 위 항목 설명을 값으로 옮겨 쓰지 마세요.

이 틀의 값만 채워서 출력하세요:
{{"team_size":"","eligibility":"","schedule":"","fee":"","prize":"","school":"","student_ok":null,"team_ok":null}}

공고 제목: {title}
공고 본문:
{body}
"""


_OLLAMA_DOWN = False  # 서버 부재 확인 후 재시도 방지


def llm_enrich(item: dict) -> dict | None:
    """Ollama 로컬 LLM으로 상세 필드 추출. 서버 없거나 실패 시 None."""
    global _OLLAMA_DOWN
    if _OLLAMA_DOWN:
        return None
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    import requests
    try:
        r = requests.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "stream": False,
                "format": "json",          # JSON 강제 출력 (Ollama 기능)
                "options": {"temperature": 0, "num_ctx": 4096},
                "messages": [{
                    "role": "user",
                    "content": EXTRACT_PROMPT.format(
                        schools=", ".join(SCHOOL_KEYWORDS.keys()),
                        title=item.get("title", ""),
                        body=item.get("body", "")[:4000],
                    ),
                }],
            },
            timeout=180,
        )
        r.raise_for_status()
        raw = (r.json().get("message") or {}).get("content", "")
        raw = re.sub(r"```(json)?", "", raw).strip()
        return json.loads(raw)
    except requests.exceptions.ConnectionError:
        log.warning("Ollama 서버 연결 불가(%s) — 규칙 기반으로만 진행", host)
        _OLLAMA_DOWN = True
        return None
    except Exception as e:
        log.warning("LLM 추출 실패(%s): %s", item.get("title", "?"), e)
        return None


UNKNOWN = "확인필요"

# 3B 모델이 '확인필요'를 흘려 쓰거나 스키마 키 이름을 값에 섞어 내보낸다.
# 실측 오염: '확인필 Keys', '확인필드', "확인필 Keys: 'school', 'student_ok'}" 등 214칸.
_JUNK = re.compile(r"확인필(?!요\b)|\bKeys?\b|student_ok|team_ok|본문이 밝힌|^[\s{\[]*$")


def _clean(s: str) -> str:
    """LLM이 흘린 값을 정리한다. 못 믿을 값은 '확인필요'로 되돌린다."""
    s = s.strip().strip("{}[]'\" \t")
    if not s or _JUNK.search(s):
        return UNKNOWN
    return s


def _text(v) -> str:
    """LLM이 뭘 돌려주든 엑셀에 넣을 수 있는 한 줄로 만든다.

    스키마로 문자열을 요구해도 dict나 list가 온다. 실제로 상금을
    {'필수 작품 시상': '…', '선택 작품 시상': '…'}로 돌려줘서 엑셀 쓰기가
    통째로 죽은 적이 있다(26분치 수집이 그 자리에서 날아갔다).
    """
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, str):
        # LLM이 dict를 문자열로 돌려주는 일도 있다 — 읽을 수 있게 편다
        t = v.strip()
        if t.startswith("{") and ":" in t:
            try:
                import ast
                return _text(ast.literal_eval(t))
            except (ValueError, SyntaxError):
                pass
        return _clean(t)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return " / ".join(t for t in (_text(x) for x in v) if t)
    if isinstance(v, dict):
        return " / ".join(f"{k}: {t}" for k, t in
                          ((k, _text(x)) for k, x in v.items()) if t)
    return str(v)


def enrich(item: dict) -> dict:
    """규칙 기반 기본값 + (가능하면) LLM 결과로 덮어쓰기."""
    item["학부"] = classify_school(item)
    item.setdefault("team_size", "확인필요")
    item.setdefault("schedule", "확인필요")
    item.setdefault("fee", "확인필요")

    llm = llm_enrich(item)
    if llm:
        item["team_size"] = _text(llm.get("team_size")) or item["team_size"]
        item["schedule"] = _text(llm.get("schedule")) or item["schedule"]
        item["fee"] = _text(llm.get("fee")) or item["fee"]
        item["prize"] = _text(llm.get("prize")) or item.get("prize", "")
        if llm.get("school") in SCHOOL_KEYWORDS:
            item["학부"] = llm["school"]
        item["eligibility_llm"] = _text(llm.get("eligibility"))
        # LLM이 명시적으로 False라고 하면 탈락 처리용 플래그
        if llm.get("student_ok") is False or llm.get("team_ok") is False:
            item["검토상태"] = "LLM판정_부적합"
    return item
