# -*- coding: utf-8 -*-
"""리서치 기준 3가지 자동 판정.

  1) 재학생 참가 가능
  2) 팀(2인 이상) 참가 가능
  3) 신청 마감까지 최소 2주 이상

규칙 기반이므로 100% 정확할 수는 없다. 판단이 애매하면 제외하지 않고
'확인필요'로 표시해 후보에 남긴다 (놓치는 것보다 낫다).

모든 필터링은 홍콩 시간대(GMT+8) 기준으로 적용됨 (HONGKONG DUE DATE 정책).
"""
import re
from datetime import date, datetime, timezone, timedelta

MIN_DAYS_LEFT = 14

RULE_KEYS = ("student_neg", "student_pos", "student_neg_en",
             "team_pos", "team_neg", "team_pos_en")
MAX_PATTERNS_PER_LIST = 30
MAX_PATTERN_LEN = 80

HK_TZ = timezone(timedelta(hours=8))  # 홍콩 시간대(GMT+8)


def get_hongkong_today():
    """홍콩 시간대 기준 오늘 날짜 반환."""
    return datetime.now(HK_TZ).date()


def validate_rules(cfg: dict):
    """규칙 후보를 검사한다. 문제가 있으면 ValueError.

    진화 엔진이 만든 것이든 손으로 고친 rules.json이든, 판정에 쓰이기 전에
    반드시 여기를 통과해야 한다. 컴파일 불가 정규식이 들어오면 예외가
    수집이 다 끝난 판정 시점에 터져 그날 실행 전체를 날린다.
    """
    if not isinstance(cfg, dict):
        raise ValueError("규칙은 dict여야 합니다")
    unknown = set(cfg) - set(RULE_KEYS)
    if unknown:
        raise ValueError(f"알 수 없는 규칙 키: {sorted(unknown)}")
    for key, pats in cfg.items():
        if not isinstance(pats, list):
            raise ValueError(f"{key}: 리스트가 아닙니다")
        if len(pats) > MAX_PATTERNS_PER_LIST:
            raise ValueError(f"{key}: 패턴이 {MAX_PATTERNS_PER_LIST}개를 넘습니다")
        for p in pats:
            if not isinstance(p, str) or not 0 < len(p) <= MAX_PATTERN_LEN:
                raise ValueError(f"{key}: 패턴이 문자열이 아니거나 "
                                 f"{MAX_PATTERN_LEN}자를 넘습니다 ({p!r})")
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError(f"{key}: 컴파일 불가 정규식 {p!r} ({e})") from None


def set_rules(cfg: dict):
    """진화 엔진이 만든 규칙으로 패턴 교체 (evolve.py, main.py에서 사용).

    검증을 먼저 하므로 실패하면 기존 규칙이 그대로 남는다 (부분 적용 없음).
    """
    global STUDENT_NEG, STUDENT_POS, STUDENT_NEG_EN, TEAM_POS, TEAM_NEG, TEAM_POS_EN
    validate_rules(cfg)
    STUDENT_NEG = cfg.get("student_neg", STUDENT_NEG)
    STUDENT_POS = cfg.get("student_pos", STUDENT_POS)
    STUDENT_NEG_EN = cfg.get("student_neg_en", STUDENT_NEG_EN)
    TEAM_POS = cfg.get("team_pos", TEAM_POS)
    TEAM_NEG = cfg.get("team_neg", TEAM_NEG)
    TEAM_POS_EN = cfg.get("team_pos_en", TEAM_POS_EN)


def get_rules() -> dict:
    return {"student_neg": STUDENT_NEG, "student_pos": STUDENT_POS,
            "student_neg_en": STUDENT_NEG_EN, "team_pos": TEAM_POS,
            "team_neg": TEAM_NEG, "team_pos_en": TEAM_POS_EN}

# 재학생 배제 신호
STUDENT_NEG = [r"대학\s*진학.*참가\s*불가", r"초·?중·?고", r"청소년\s*(만|대상)",
               r"임직원\s*(만|대상|한정)", r"기업\s*(만|대상|한정)", r"석·?박사\s*만"]
STUDENT_POS = [r"대학생", r"대학원생", r"재학생", r"제한\s*없", r"누구나", r"청년",
               r"(?i)university\s+students?", r"(?i)college\s+students?",
               r"(?i)open\s+to\s+(the\s+)?public", r"(?i)students?\s+(and|&)"]
STUDENT_NEG_EN = [r"(?i)high\s*school\s+only", r"(?i)employees?\s+only",
                  r"(?i)under\s*18\s+only", r"(?i)K-?12\s+only"]

# 팀 참가 신호
TEAM_POS = [r"\d+\s*[~∼〜–-]\s*\d+\s*인", r"팀\s*(참가|단위|구성|접수)",
            r"\d+\s*인\s*이상", r"팀\s*\(\s*\d", r"개인\s*또는\s*팀", r"팀별"]
TEAM_NEG = [r"개인\s*(참가|접수)만", r"1\s*인\s*(참가|한정)", r"팀\s*참가\s*불가",
            r"(?i)individuals?\s+only", r"(?i)solo\s+only", r"(?i)no\s+teams?"]
TEAM_POS_EN = [r"(?i)teams?\s+of\s+\d", r"(?i)per\s+team", r"(?i)team\s+members?",
               r"(?i)up\s+to\s+\d+\s+(people|members|hackers)"]


def _parse_date(s: str | None):
    if not s:
        return None
    s = re.sub(r"[./]", "-", s).strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def check_deadline(item: dict, today: date | None = None) -> tuple[str, int | None]:
    """→ ('통과'|'탈락'|'확인필요', 남은 일수)"""
    today = today or date.today()
    d = _parse_date(item.get("deadline"))
    if d is None:
        return "확인필요", None
    left = (d - today).days
    return ("통과" if left >= MIN_DAYS_LEFT else "탈락"), left


def check_student(item: dict) -> str:
    text = f"{item.get('target','')} {item.get('body','')[:3000]}"
    negs = STUDENT_NEG + STUDENT_NEG_EN
    if any(re.search(p, text) for p in negs):
        return "탈락"
    if any(re.search(p, text) for p in STUDENT_POS):
        return "통과"
    # 해외(Devpost) 해커톤은 대부분 대학생 참가 가능하나 공고별 확인 필요
    return "확인필요"


def check_team(item: dict) -> str:
    text = item.get("body", "")[:5000]
    # NEG 우선 (check_student과 동일). 예전엔 'NEG면서 POS가 없을 때'만 탈락시켰는데,
    # "팀 참가 불가"·"팀 접수는 받지 않습니다" 같은 부정문 안의 '팀 참가'가 POS로
    # 잡혀 배제 문구를 무력화했다.
    if any(re.search(p, text) for p in TEAM_NEG):
        return "탈락"
    if any(re.search(p, text) for p in TEAM_POS + TEAM_POS_EN):
        return "통과"
    # 해외 해커톤은 통상 팀 허용이지만 공고별 확인이 필요하므로 국내와 동일 처리
    return "확인필요"


def apply_filters(items: list[dict], today: date | None = None) -> list[dict]:
    """탈락 건 제거, 나머지에 판정 결과 부착.

    홍콩 시간대(GMT+8) 기준으로 필터링. today가 명시되지 않으면 홍콩 오늘 날짜 사용.
    """
    # today가 명시되지 않으면 항상 홍콩 시간대 기준
    if today is None:
        today = get_hongkong_today()

    kept = []
    for it in items:
        dl_status, days_left = check_deadline(it, today)
        st = check_student(it)
        tm = check_team(it)
        if "탈락" in (dl_status, st, tm):
            continue
        it["days_left"] = days_left
        it["판정_마감"] = dl_status
        it["판정_재학생"] = st
        it["판정_팀"] = tm
        it["검토상태"] = "자동통과" if (dl_status == st == tm == "통과") else "확인필요"
        kept.append(it)
    return kept
