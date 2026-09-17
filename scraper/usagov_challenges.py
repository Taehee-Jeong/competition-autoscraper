# -*- coding: utf-8 -*-
"""
USA.gov 연방 공모전(challenge) 스크래퍼 — 폐지된 Challenge.gov의 공식 후속 사이트.

URL 구조 (2026-07 실측):
  - 목록:  https://www.usa.gov/find-active-challenge   (페이지네이션 없음, 활성 10건 전량)
  - 상세:  https://www.usa.gov/challenges/{slug}

주의 2가지:
  1) robots.txt에 `Crawl-delay: 10`이 명시돼 있다. 다른 소스(1초)와 달리 요청 간
     10초를 지켜야 위반이 아니다 → DELAY 기본값 10.0. 전량 수집 시 약 2분 소요.
  2) 응모대상(target) 원문이 페이지에 없다. 본문이 "자격요건은 주관기관 공고
     페이지를 보라"고만 하고 외부로 넘기므로 target은 빈 문자열로 둔다.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

log = logging.getLogger("usagov_challenges")

BASE = "https://www.usa.gov"
LIST_URL = f"{BASE}/find-active-challenge"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# robots.txt: Crawl-delay: 10 (2026-07 실측). 이보다 짧게 두면 robots 위반이다.
DELAY = 10.0

# 공고 본문 영역 (2026-07 실측). soup.find("main")은 2,275자인데 좌측 사이드바에
# 다른 공모 10건의 제목이 통째로 섞여 들어와, 다운스트림 정규식이 남의 공고
# 제목을 잡는다. #main-content도 main과 동일하므로 이 클래스만 써야 한다.
BODY_CLASS = "usa-layout-docs__main"
# 본문 끝에 붙는 사이트 공통 꼬리(공유 버튼·문의 안내·갱신일)를 잘라낸다.
TAIL_MARKERS = ("SHARE THIS PAGE", "LAST UPDATED")

# 상세 페이지 'Key information' 표의 라벨. 값이 여러 줄인 항목(Challenge type)이
# 있어서 "다음 라벨이 나올 때까지"를 값으로 잡는다.
LABELS = ["Key information", "Sponsoring agency", "Start date", "End date",
          "Challenge type", "Prizes", "Contact"]
# 표가 끝났음을 알리는 줄들 (법적 고지 문단 / 신청 링크 / 갱신일)
STOP_PREFIXES = ("Apply for", "These federal prize", "LAST UPDATED")


def _get(url: str, delay: float = DELAY) -> BeautifulSoup:
    """예의 있는 요청: 요청 뒤 delay(기본 10초, robots 준수)를 두고 1회 재시도."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            time.sleep(delay)
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning("요청 실패(%s/2): %s (%s)", attempt + 1, url, e)
            time.sleep(delay)
    raise RuntimeError(f"페이지 요청 실패: {url}")


def list_challenge_paths(pages: int = 1) -> list[str]:
    """목록에서 상세 경로('/challenges/{slug}') 수집.

    이 사이트는 페이지네이션이 없어 활성 공모 전량이 한 페이지에 있다.
    pages 인자는 다른 소스와 시그니처를 맞추기 위한 것으로 실제로 쓰이지 않는다.
    허브 링크 '/challenges' 자체는 상세가 아니므로 제외한다.
    """
    soup = _get(LIST_URL)
    root = soup.find("main") or soup
    paths: list[str] = []
    seen: set[str] = set()
    for a in root.find_all("a", href=True):
        href = a["href"].split("?")[0].rstrip("/")
        if not href.startswith("/challenges/"):
            continue
        if href not in seen:
            seen.add(href)
            paths.append(href)
    log.info("목록: 활성 공모 %d건", len(paths))
    return paths


def _section(lines: list[str], label: str) -> str:
    """'Key information' 표에서 라벨 다음 줄부터 다음 라벨 전까지를 값으로 반환."""
    if label not in lines:
        return ""
    vals = []
    for ln in lines[lines.index(label) + 1:]:
        if ln in LABELS or ln.startswith(STOP_PREFIXES):
            break
        vals.append(ln)
    return ", ".join(vals)[:300]


def _parse_end_date(end_date: str) -> str | None:
    """'8/10/2026 5:00 PM ET' → '2026-08-10'.

    실측상 zero-pad가 섞여 있어('06/24/2026'와 '8/10/2026') \\d{1,2} + int()로 정규화.
    """
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", end_date or "")
    if not m:
        return None
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"


def fetch_challenge_detail(path: str) -> dict:
    """상세 페이지 1건 파싱 → 공통 스키마 dict."""
    url = urljoin(BASE, path)
    soup = _get(url)

    h1 = soup.select_one("main h1")
    title = h1.get_text(strip=True) if h1 else ""

    node = soup.find("div", class_=BODY_CLASS)
    if node is None:
        # 전체 텍스트로 폴백하면 사이드바의 다른 공모 제목이 섞이므로 폴백하지 않는다.
        log.warning("본문 영역(.%s) 없음 — 요약으로 대체 %s", BODY_CLASS, path)
        return {
            "ix": "usagov-" + path.rsplit("/", 1)[-1],
            "url": url, "homepage": url, "title": title,
            "field": "", "target": "", "host": "", "period": "", "prize": "",
            "deadline": None, "location": "",
            "body": f"{title} | 분야: | 기간: ",
        }

    body = node.get_text("\n", strip=True)
    for marker in TAIL_MARKERS:
        body = body.split(marker)[0]
    body = body.strip()
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]

    start, end = _section(lines, "Start date"), _section(lines, "End date")
    ctype = _section(lines, "Challenge type")

    # 홈페이지: 'Apply for ...' 앵커가 실제 주관기관 공고 페이지다(자격요건 원문 소재).
    homepage = url
    for a in node.find_all("a", href=True):
        if a.get_text(strip=True).startswith("Apply for") and a["href"].startswith("http"):
            homepage = a["href"]
            break

    return {
        "ix": "usagov-" + path.rsplit("/", 1)[-1],
        "url": url,
        "homepage": homepage,
        "title": title,
        "field": f"연방 공모전 / {ctype}" if ctype else "연방 공모전",
        "target": "",  # 페이지에 자격요건 원문 없음 (주관기관 페이지로 넘김)
        "host": _section(lines, "Sponsoring agency"),
        "period": f"{start} ~ {end}".strip(" ~"),
        "prize": _section(lines, "Prizes"),
        "deadline": _parse_end_date(end),
        "location": "",
        "body": body[:8000],
    }


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """활성 연방 공모전 수집 → 공통 스키마 dict 리스트."""
    paths = list_challenge_paths(pages=pages)
    results = []
    for path in paths[:max_details]:
        try:
            item = fetch_challenge_detail(path)
            item["source"] = "USA.gov 연방공모전(해외)"
            item["lang"] = "en"
            results.append(item)
        except Exception as e:
            log.warning("상세 파싱 실패 %s: %s", path, e)
    log.info("[USA.gov] 상세 수집 완료: %d건", len(results))
    return results
