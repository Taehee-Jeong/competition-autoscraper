# -*- coding: utf-8 -*-
"""HKSTP(홍콩과학기술단지) 이벤트 중 대회성 건 수집 — sitemap 경유.

이벤트 목록 HTML은 JS 렌더링이고 내부 API(/api/List/NewsEventSearch)는 파라미터를
추측할 수 없어, 대신 https://www.hkstp.org/sitemap.xml (약 2.8 MB, <lastmod> 포함)에서
`/en/park-life/news-and-events/events/<slug>` URL을 뽑는다. 상세 페이지는 서버 렌더링이다.

상세 구조 (2026-09-13 실측):
  .detail-two-third
      .title  a.tag("Past Events" / "Featured Events") · .date · h1 · 공유버튼
      .content .info   div.label(Date/Time/Venue) + div.desc 짝
      .content .image-content   본문
sitemap 에는 지난 행사가 대부분이라 상태 라벨이 Past 이거나 종료일이 오늘 이전이면 버린다.

프록시: hkust 모듈과 같은 이유로 환경변수 프록시를 무시하는 세션을 쓴다.
"""
import re
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from scraper.hkust import parse_en_date, deadline_from_body, HEADERS
from scraper.hkubs import block_text

log = logging.getLogger("hkstp")

BASE = "https://www.hkstp.org"
SITEMAP = f"{BASE}/sitemap.xml"
EVENT_PREFIX = f"{BASE}/en/park-life/news-and-events/events/"
SOURCE = "HKSTP(홍콩)"
HKT = timezone(timedelta(hours=8))

_URL_ENTRY = re.compile(
    r"<loc>(https://www\.hkstp\.org/en/park-life/news-and-events/events/[A-Za-z0-9_-]+)</loc>"
    r"\s*<lastmod>([^<]+)</lastmod>")
COMPETITION_SLUG = re.compile(
    r"(?i)competition|contest|hackathon|challenge|pitch|award|cup|techathon|epic|ideathon|datathon")
_ORGANISER = re.compile(
    r"(?i)\b(?:co-)?(?:organi[sz]ed|hosted|presented)\s+by\s+(?:the\s+)?([A-Z][^,.\n(]{2,80})")
_MONEY = re.compile(r"(?i)(HK\$|US\$|USD|HKD|\$)\s?\d[\d,]*[MK]?")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False          # HTTPS_PROXY 무시 (모듈 docstring 참고)
    s.headers.update(HEADERS)
    return s


def _get(sess: requests.Session, url: str, delay: float = 1.0, timeout: int = 25) -> str:
    r = sess.get(url, timeout=timeout)
    r.raise_for_status()
    time.sleep(delay)
    return r.text


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# ── sitemap ───────────────────────────────────────────────────────────────
def sitemap_event_urls(xml_text: str) -> list[tuple[str, str]]:
    """sitemap XML → [(url, lastmod)] — 이벤트 상세(단일 slug)만, 순서는 파일 순."""
    return [(u, l) for u, l in _URL_ENTRY.findall(xml_text)]


def competition_urls(xml_text: str) -> list[tuple[str, str]]:
    """대회성 slug 만 남겨 lastmod 내림차순."""
    ev = {u: l for u, l in sitemap_event_urls(xml_text)
          if COMPETITION_SLUG.search(u[len(EVENT_PREFIX):])}
    return sorted(ev.items(), key=lambda t: t[1], reverse=True)


# ── 상세 ─────────────────────────────────────────────────────────────────
def _info_rows(main) -> dict:
    """div.label / div.desc 짝 → {'date': ..., 'time': ..., 'venue': ...}."""
    rows = {}
    for lab in main.select(".info .label"):
        desc = lab.find_next_sibling(class_="desc")
        if desc is not None:
            rows[_clean(lab.get_text()).lower()] = _clean(desc.get_text(" ", strip=True))
    return rows


def _date_range(text: str) -> tuple[str | None, str | None]:
    """'17 Mar 2025 - 17 Jun 2025' / '21 Jun 2026' → (시작, 종료)."""
    parts = re.split(r"\s+[-–—]\s+", text or "")
    dates = [parse_en_date(p) for p in parts]
    dates = [d for d in dates if d]
    if not dates:
        return None, None
    return dates[0], dates[-1]


def parse_detail(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one(".detail-two-third") or soup
    h1 = main.find("h1")
    og = soup.find("meta", property="og:title")
    title = (_clean(h1.get_text(" ", strip=True)) if h1
             else _clean(og["content"]) if og and og.get("content")
             else _clean(soup.title.get_text()) if soup.title else "")
    status = " ".join(_clean(t.get_text()) for t in main.select(".title .tag, a.tag"))
    rows = _info_rows(main)
    date_text = rows.get("date") or (_clean(main.select_one(".date").get_text())
                                     if main.select_one(".date") else "")
    start, end = _date_range(date_text)
    venue = rows.get("venue", "")

    # 신형 템플릿은 .image-content, 2023년 이전 구형 템플릿은 .info.richtext > .subContent
    node = main.select_one(".image-content") or main.select_one(".content .subContent")
    if node is not None:
        body = block_text(node)
    else:
        log.warning("HKSTP 본문 없음: %s", url)
        body = f"{title} | date: {date_text} | venue: {venue}"

    m = _ORGANISER.search(body)
    prizes = [l.strip()[:120] for l in body.split("\n") if _MONEY.search(l)][:3]
    return {
        "source": SOURCE,
        "ix": "hkstp-" + url.rstrip("/").rsplit("/", 1)[-1],
        "url": url,
        "homepage": url,
        "title": title,
        "field": "과학기술·창업 (HKSTP 이벤트)",
        "target": "확인필요 (본문 참고)",
        "host": _clean(m.group(1)) if m else "HKSTP",
        "period": date_text,
        "prize": " / ".join(prizes),
        # 본문의 명시적 마감(연도 포함) 우선, 없으면 행사 시작일.
        # 'Application deadline:' 과 날짜가 다른 태그에 있어 줄이 갈리므로 한 줄로 합쳐 찾는다.
        "deadline": deadline_from_body(_clean(body)) or start,
        "body": body,
        "lang": "en",
        "location": venue or "홍콩 (HKSTP)",
        "status": status,
        "end_date": end,
    }


def is_past(item: dict, today: str | None = None) -> bool:
    """상태 라벨이 Past 이거나 종료일(없으면 마감일)이 오늘 이전이면 True."""
    if "past" in (item.get("status") or "").lower():
        return True
    today = today or datetime.now(HKT).strftime("%Y-%m-%d")
    last = item.get("end_date") or item.get("deadline")
    return bool(last and last < today)


# ── 진입점 ────────────────────────────────────────────────────────────────
def scrape(pages: int = 1, max_details: int = 25, delay: float = 1.0) -> list[dict]:
    """sitemap → 대회성 이벤트 상세 → 진행 중인 건만 공통 스키마 dict 리스트."""
    sess = _session()
    try:
        cands = competition_urls(_get(sess, SITEMAP, delay, timeout=60))
    except Exception as e:
        log.warning("HKSTP sitemap 실패: %s", e)
        return []
    log.info("HKSTP sitemap: 대회성 이벤트 %d건", len(cands))

    items = []
    for url, _ in cands[:max_details]:
        try:
            it = parse_detail(_get(sess, url, delay), url)
        except Exception as e:
            log.warning("HKSTP 상세 실패 %s: %s", url, e)
            continue
        if is_past(it):
            log.info("지난 행사 건너뜀(%s, %s): %s", it["status"], it["end_date"], it["title"])
            continue
        items.append(it)
    log.info("HKSTP: %d건", len(items))
    return items
