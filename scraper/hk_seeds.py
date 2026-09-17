# -*- coding: utf-8 -*-
"""홍콩 주요대회 '고정 시드' 수집 — 목록 페이지가 없는 연례 대회들.

Techathon+, Hack4SDG, PolyU IFC 같은 홍콩 전역 대회는 각자 단일 사이트에만 공고가 올라와서
크롤링할 목록이 없다. 그래서 대회별 페이지(SEEDS)를 매 실행 때 직접 열어 올해 날짜·마감·자격
문구를 정규식으로 뽑고, 시드당 1건씩 공통 스키마로 낸다.

  - 마감: hkust.deadline_from_body(본문) → 시드별 deadline_regex → 그래도 없으면 None
    (파이프라인이 '확인필요'로 표시; 연도는 절대 추정하지 않는다).
  - 페이지를 못 열면 정적 정보 + body="(page unreachable) …" 로 그래도 낸다
    (연례 대회라 보여주는 가치가 있음).
  - body는 페이지 전체가 아니라 시드마다 지정한 본문 컨테이너 텍스트만 (DEVELOPMENT.md §8).

프록시: hkust.py와 같은 이유로 셸의 HTTPS_PROXY를 무시하는 세션을 쓴다.
"""
import re
import time
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from scraper.hkust import HEADERS, HKT, parse_en_date, deadline_from_body

log = logging.getLogger("hk_seeds")

SOURCE = "홍콩 주요대회(홍콩)"
BODY_MAX = 8000
MIN_TEXT = 200          # 이보다 짧으면 본문을 못 찾은 것으로 본다 (JS 전용 페이지 등)

# 시드 정규식에서 날짜 자리에 쓰는 캡처 그룹.
# '11 Jan 2027' / 'Jan 11, 2027' / 'January 11, 2027' / '26-Oct-2026' / '2026-10-26'
_D = (r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9},?\s+\d{4}"
      r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
      r"|\d{1,2}-[A-Za-z]{3,9}-\d{4}"
      r"|\d{4}-\d{2}-\d{2})")
_APP_DEADLINE = r"(?i)Application Deadline\s*:?\s*" + _D
_YEAR = re.compile(r"\b(20[2-4]\d(?:-\d{2})?)\b")          # '2026' 또는 '2026-27'
# 자격 문장: 앞쪽은 같은 줄 안에서만, 뒤쪽은 줄을 넘어 마침표까지 (헤딩 'Who Can Apply' + 다음 줄)
_ELIG = re.compile(r"(?i)([^.\n]{0,100}\b(?:open to|eligible|who can apply|welcome to join"
                   r"|invites all students|nominate one team)\b[^.]{0,200})")
_AMOUNT = re.compile(r"(?i)(HK\$|US\$|\$|HKD|USD)\s?\d")

EC = "https://ec.hkust.edu.hk/events/"
POLYU = "https://www.polyu.edu.hk/kteo/competitions-and-events/polyu-ifc/polyu-ifc-{year}/"

# urls: (페이지, 본문 CSS 선택자) — 순서대로 이어 붙여 body가 된다.
# fallback_urls: 위 페이지가 전부 실패/빈 내용일 때만 시도.
# {year}/{prev}: 실행 시점(홍콩시간) 연도 / 그 전해, {yy}/{yynext}: 두 자리 연도 / 다음 해 (HKSEC '2026-27').
# prefer_regex: 본문에 deadline_from_body가 잘못 무는 미끼 문구가 있을 때 시드 정규식을 먼저 쓴다.
SEEDS = [
    {"key": "techathon", "title": "Hong Kong Techathon+",
     "desc": "HKSTP and 15 Hong Kong universities' annual cross-university AI/tech "
             "entrepreneurship competition. Finale at Hong Kong Science Park.",
     "urls": [("https://www.hktechathon.com/en", "#indexAbout, .box-keydates"),
              ("https://www.hktechathon.com/en/site/join", "main")],
     "homepage": "https://www.hktechathon.com/en",
     "host": "HKSTP + 15 universities (incl. HKUST)", "field": "AI·기술창업 (해커톤/피칭)",
     "target": "Students, alumni, researchers and professors of co-organising universities "
               "(incl. HKUST); cross-university teams of 2-6 allowed",
     "location": "홍콩 (Hong Kong Science Park)",
     # 홈 Key Dates는 날짜가 라벨 '앞'에 온다: 'Jan 11, 2027 / at 23:59 / Deadline of Team Formation …'
     "deadline_regex": _D + r"\s*(?:at\s+[\d:]+\s*)?Deadline of Team Formation",
     "dates": [("Deadline", _D + r"\s*(?:at\s+[\d:]+\s*)?Deadline of Team Formation"),
               ("Result", _D + r"\s*Result Announcement")]},

    {"key": "hack4sdg", "title": "Inter-University GenAI Hackathon for SDGs",
     "desc": "Extended 5-week GenAI hackathon by Hong Kong's eight UGC-funded universities. "
             "Register via own university; teams of 3-5 formed on launch day.",
     "urls": [("https://www.hack4sdg.com/", ".entry-content"),
              ("https://www.hack4sdg.com/eligibility-rules/", ".entry-content"),
              ("https://www.hack4sdg.com/{year}-roadmap/", ".entry-content")],
     "homepage": "https://www.hack4sdg.com/",
     "host": "8 UGC-funded universities (HKU, CUHK, HKUST, CityU, PolyU, HKBU, LingU, EdUHK)",
     "field": "생성형 AI·SDGs 해커톤",
     "target": "UG/PG students of the 8 participating universities; teams 3-5 (>=50% UG); "
               "register through own university",
     "location": "홍콩 (launch @ HKU, final @ CityU)",
     "deadline_regex": r"(?i)launch day\s*\(?" + _D,
     "dates": [("Launch", r"(?i)launch day\s*\(?" + _D),
               ("Final", r"(?i)demo day\s*\(?" + _D)]},

    {"key": "polyu_ifc", "title": "PolyU International Future Challenge",
     "desc": "PolyU KTEO's international innovation/entrepreneurship challenge with regional "
             "rounds (Hong Kong Region) and a Grand Final.",
     "urls": [(POLYU.format(year="{year}"), "main")],
     "fallback_urls": [(POLYU.format(year="{prev}"), "main")],
     "homepage": "https://www.polyu.edu.hk/kteo/competitions-and-events/polyu-ifc/",
     "host": "PolyU Knowledge Transfer and Entrepreneurship Office",
     "field": "기술창업·혁신 (5 industry domains)",
     "target": "Startup/innovation teams applying to the Hong Kong Region round",
     "location": "홍콩 (Hong Kong Region) + Grand Final",
     "prefer_regex": True,  # 홍콩 지역만 추출하기 위해 정규식 우선 (여러 지역 마감이 있음)
     "deadline_regex": r"(?i)Hong Kong Region\s*:?\s*" + _D,  # 케이스 인센서티브
     "dates": [("HK deadline", r"(?i)Hong Kong Region\s*:?\s*" + _D),
               ("Grand Final", r"(?i)Grand Final Date\s*:?\s*" + _D)]},

    {"key": "hkict_student", "title": "Hong Kong ICT Awards: Student Innovation Award",
     "desc": "Government-steered ICT awards; Student Innovation Award Stream 3 (Higher "
             "Education) for all tertiary students. HKUST EC mirror page.",
     "urls": [(EC + "hong-kong-ict-awards-{year}-student-innovation-award", ".field--name-body")],
     "fallback_urls": [(EC + "hong-kong-ict-awards-{prev}-student-innovation-award",
                        ".field--name-body")],
     "host": "OGCIO / HKITDA (Student Innovation Award)", "field": "ICT·학생 혁신",
     "target": "All current tertiary students (UG/PG/doctoral) — Stream 3: Higher Education",
     "location": "홍콩",
     "deadline_regex": r"(?i)Enrol?l?ment Deadline\s*:?\s*" + _D,
     "dates": [("Enrolment deadline", r"(?i)Enrol?l?ment Deadline\s*:?\s*" + _D)]},

    {"key": "cupp", "title": "Cyberport University Partnership Programme (CUPP)",
     "desc": "Cyberport's training + competition programme for university teams; HK$100,000 "
             "CCMF grant; themes AI, Blockchain, Cybersecurity, Data Science. Nomination via HKUST EC.",
     "urls": [(EC + "cyberport-university-partnership-programme-cupp-{year}", ".field--name-body")],
     "fallback_urls": [(EC + "cyberport-university-partnership-programme-cupp-{prev}",
                        ".field--name-body")],
     "host": "Cyberport (HKUST nomination via Entrepreneurship Center)",
     "field": "디지털테크 창업 (AI/블록체인/사이버보안/데이터)",
     "target": "Current UG/PG students or graduates aged 18-30, nominated by co-organising "
               "universities; teams up to 5",
     "location": "홍콩 (boot camp at LSE, London)",
     # 본문의 'Registration deadline: 2 Feb 2026'는 설명회 등록 마감(미끼) → 시드 정규식 우선
     "prefer_regex": True,
     "deadline_regex": r"(?i)HKUST Nomination[^\n]{0,20}\s*" + _D,
     "dates": [("HKUST nomination deadline", r"(?i)HKUST Nomination[^\n]{0,20}\s*" + _D)]},

    {"key": "hksec", "title": "Hong Kong Social Enterprise Challenge (HKSEC)",
     "desc": "Hong Kong-wide social enterprise business plan competition for tertiary students "
             "aged 18-35 (teams 2-4), run by CUHK Centre for Entrepreneurship.",
     "urls": [("https://entrepreneurship.bschool.cuhk.edu.hk/news/"
               "hong-kong-social-enterprise-challenge-hksec-{year}-{yynext}/", "article")],
     "fallback_urls": [("https://entrepreneurship.bschool.cuhk.edu.hk/news/"
                        "hong-kong-social-enterprise-challenge-hksec-{prev}-{yy}/", "article")],
     "homepage": "https://www.hksec.hk/",
     "host": "CUHK Centre for Entrepreneurship", "field": "사회적기업 창업",
     "target": "All Hong Kong tertiary students, aged 18-35, teams of 2-4",
     "location": "홍콩",
     "deadline_regex": _APP_DEADLINE,
     "dates": [("Application deadline", _APP_DEADLINE)]},

    {"key": "cathay_hackathon", "title": "Cathay Hackathon",
     "desc": "Cathay Pacific's 24-hour aviation hackathon for students and recent graduates.",
     # 공식 사이트는 JS 전용(본문 없음) → HKUST 캘린더 게시물로 폴백
     "urls": [("https://hackathon.cathaypacific.com/en_HK/", "main, body")],
     "fallback_urls": [("https://calendar.hkust.edu.hk/events/cathay-hackathon-{year}",
                        ".field--name-body")],
     "homepage": "https://hackathon.cathaypacific.com/en_HK/",
     "host": "Cathay Pacific", "field": "항공·IT 해커톤",
     "target": "All UG/PG students and recent graduates (within two years)",
     "location": "홍콩 (+ Shenzhen master class)",
     "deadline_regex": _APP_DEADLINE,
     "dates": [("Application deadline", _APP_DEADLINE)]},

    {"key": "bnp_hackathon", "title": "BNP Paribas Sustainable Finance Hackathon Hong Kong",
     "desc": "BNP Paribas Hong Kong's sustainable finance hackathon for CUHK/CityU/HKU/HKUST "
             "students in penultimate year or above.",
     "urls": [("https://www.bnpparibas.com.hk/en/about-us/sustainable-finance/"
               "university-hackathon/", ".blocks-container")],
     "host": "BNP Paribas Hong Kong", "field": "지속가능금융 해커톤",
     "target": "CUHK, CityU, HKU, HKUST students in penultimate undergraduate year or higher "
               "(incl. postgraduates)",
     "location": "홍콩 (BNP Paribas office)",
     "deadline_regex": r"(?i)proposals?\s+(?:responding to the problem statement\s+)?by\s+" + _D,
     "dates": [("Proposal deadline",
                r"(?i)proposals?\s+(?:responding to the problem statement\s+)?by\s+" + _D),
               ("Hackathon day", r"(?i)whole-day event on\s+" + _D)]},

    {"key": "hsbc_hku_case", "title": "HSBC/HKU Business Case Competition Hong Kong",
     "desc": "One-day business case competition; each Hong Kong university nominates one team "
             "of four full-time undergraduates (apply through your own school).",
     "urls": [("https://competition.acrc.hku.hk/LocalCompetitions/Overview", ".content-main")],
     "homepage": "https://competition.acrc.hku.hk/",
     "host": "HKU Asia Case Research Centre / HSBC", "field": "비즈니스 케이스",
     "target": "Full-time undergraduates nominated by their university (one team of 4 per "
               "university); no direct application",
     "location": "홍콩 (HSBC Main Building)",
     "dates": []},
]


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False          # HTTPS_PROXY 무시 (hkust.py docstring 참고)
    s.headers.update(HEADERS)
    return s


def _get(sess: requests.Session, url: str, delay: float) -> str:
    r = sess.get(url, timeout=25)
    r.raise_for_status()
    time.sleep(delay)
    return r.text


# ── 텍스트 추출 ───────────────────────────────────────────────────────────
def page_text(html: str, selector: str) -> tuple[BeautifulSoup, str]:
    """선택자에 맞는 본문 요소들의 텍스트(문서 순서). 없으면 ''."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    parts = [n.get_text("\n", strip=True) for n in soup.select(selector)]
    text = re.sub(r"[ \t\xa0]+", " ", "\n".join(p for p in parts if p))
    return soup, text


def find_date(text: str, pattern: str | None) -> tuple[str | None, str]:
    """pattern의 캡처 그룹(날짜)을 파싱 → ('YYYY-MM-DD', 원문). 첫 파싱 성공분."""
    if not pattern:
        return None, ""
    for m in re.finditer(pattern, text):
        raw = next((g for g in m.groups() if g), m.group(0))
        raw = re.sub(r"\s+", " ", raw)
        d = parse_en_date(re.sub(r"(\d{1,2})-([A-Za-z]{3,9})-(\d{4})", r"\1 \2 \3", raw))
        if d:
            return d, raw
    return None, ""


def detect_year(soup: BeautifulSoup, text: str) -> str | None:
    """<title> → h1 → 본문 첫 150자 순으로 '2026'/'2026-27' 형태의 연도."""
    cands = [soup.title.get_text(" ", strip=True) if soup.title else ""]
    cands += [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    cands.append(text[:150])
    for c in cands:
        m = _YEAR.search(c)
        if m:
            return m.group(1)
    return None


def _prize(text: str) -> str:
    """금액이 있고 상금·지원 낱말이 같은 줄에 있는 첫 줄, 금액 주변 240자."""
    for line in text.split("\n"):
        m = _AMOUNT.search(line)
        if m and re.search(r"(?i)prize|fund|grant|award|cash|win|seed|support", line):
            start = max(0, m.start() - 120)
            return line[start:start + 240].strip()
    return ""


def _eligibility(text: str) -> str:
    m = _ELIG.search(text)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# ── 시드 → 항목 ───────────────────────────────────────────────────────────
def build_item(seed: dict, pages: list[tuple[str, str, str]], url: str | None = None) -> dict:
    """pages = [(url, html, selector)] (내용이 있는 것만). 비어 있으면 unreachable 항목."""
    url = pages[0][0] if pages else (url or seed["urls"][0][0])
    title, year, texts = seed["title"], None, []
    for _, html, selector in pages:
        soup, text = page_text(html, selector)
        texts.append(text)
        year = year or detect_year(soup, text)
    text = "\n".join(texts)
    if year and year[:4] not in title:
        title = f"{title} {year}"

    if not pages:
        deadline, period, prize, target = None, "", "", seed["target"]
        body = "(page unreachable) " + seed["desc"]
    else:
        first, second = deadline_from_body, lambda t: find_date(t, seed.get("deadline_regex"))[0]
        if seed.get("prefer_regex"):
            first, second = second, first
        deadline = first(text) or second(text)
        found = [(label, find_date(text, pat)[1]) for label, pat in seed["dates"]]
        period = " · ".join(f"{label} {raw}" for label, raw in found if raw)
        prize = _prize(text)
        elig = _eligibility(text)
        target = f"{seed['target']} — {elig}" if elig else seed["target"]
        body = text[:BODY_MAX]
    return {
        "source": SOURCE,
        "ix": f"hkseed-{seed['key']}",
        "url": url,
        "homepage": seed.get("homepage") or url,
        "title": title,
        "field": seed["field"],
        "target": target,
        "host": seed["host"],
        "period": period,
        "prize": prize,
        "deadline": deadline,
        "body": body,
        "lang": "en",
        "location": seed["location"],
    }


def fetch_seed(sess: requests.Session, seed: dict, delay: float = 1.0) -> dict:
    """시드 페이지들을 열어 항목 하나로. 1차 URL이 전부 실패/빈 내용이면 fallback_urls."""
    year = datetime.now(HKT).year
    fmt = {"year": year, "prev": year - 1, "yy": f"{year % 100:02d}", "yynext": f"{(year + 1) % 100:02d}"}
    pages = []
    for group in (seed["urls"], seed.get("fallback_urls", [])):
        for url, selector in group:
            url = url.format(**fmt)
            try:
                html = _get(sess, url, delay)
            except Exception as e:  # noqa: BLE001
                log.warning("%s: 페이지 실패 %s: %s", seed["key"], url, e)
                continue
            if len(page_text(html, selector)[1]) < MIN_TEXT:
                log.warning("%s: 본문 없음(%s) %s", seed["key"], selector, url)
                continue
            pages.append((url, html, selector))
        if pages:
            break
    if not pages:
        log.warning("%s: 모든 페이지 실패 → 정적 정보로 출력", seed["key"])
    return build_item(seed, pages, seed["urls"][0][0].format(**fmt))


def scrape(pages: int = 1, max_details: int = 20, delay: float = 1.0) -> list[dict]:
    """SEEDS 각각 1건 → 공통 스키마 dict 리스트. (pages는 다른 소스와 시그니처 통일용)"""
    sess = _session()
    items = []
    for seed in SEEDS[:max_details]:
        it = fetch_seed(sess, seed, delay)
        log.info("%s: %s | deadline=%s | %s", seed["key"], it["title"], it["deadline"], it["period"])
        items.append(it)
    log.info("홍콩 주요대회 시드: %d건", len(items))
    return items
