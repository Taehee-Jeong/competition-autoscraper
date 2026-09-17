# -*- coding: utf-8 -*-
"""Eventbrite 홍콩 이벤트 중 해커톤·대회 수집.

  목록  https://www.eventbrite.hk/d/hong-kong-sar/<키워드>/?page=N
      플레인 UA로 200. HTML 안의 `window.__SERVER_DATA__ = {...};` JSON에
      search_data.events.{pagination, results[]} 가 들어 있다. results[].full_description 은
      목록에선 비어 있다.
      주의: 경로/q 키워드는 필터가 아니라 랭커라(어떤 단어든 ~900건 보고) 결과는
      대부분 워크숍·밋업이다. 그래서 name+summary+tags 가 대회 정규식에 걸리는 건만 남긴다.
  상세  results[].url  (eventbrite.com/e/...-tickets-<id>)
      `<script id="__NEXT_DATA__">` → props.pageProps.context.
        basicInfo.organizer.name          주최
        structuredContent.modules[].text  본문 HTML
        seo.offersSchema[0].availabilityEnds  티켓 판매 종료(UTC) = 등록 마감

프록시: hkust 모듈과 같은 이유로 환경변수 프록시(HTTPS_PROXY)를 무시하는 세션을 쓴다.
"""
import re
import json
import time
import logging

import requests
from bs4 import BeautifulSoup

from scraper.hkust import iso_to_hk_date, _prize_lines

log = logging.getLogger("eventbrite")

BASE = "https://www.eventbrite.hk"
LIST_KEYWORDS = ["hackathon", "competition"]
# Eventbrite 자체 '형식' 분류표. 트리비아 나이트·보드게임 모임에 다 붙어 있어 매칭에서 뺀다
# (주최자가 직접 단 태그는 그대로 본다).
FORMAT_TAGS_IGNORED = {"Game or Competition"}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
BODY_MAX = 8000

SERVER_DATA_RE = re.compile(r"window\.__SERVER_DATA__\s*=\s*(\{.*?\});\s*\n", re.S)
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

COMPETITION_RE = re.compile(
    r"(?i)\b(hackathon|competition|challenge|contest|ideathon|datathon"
    r"|pitch(ing)?( competition| contest| day)?|olympiads?|case comp|demo day)\b")


def is_competition_text(title: str, body: str) -> bool:
    return bool(COMPETITION_RE.search(f"{title}\n{body}"))


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False          # HTTPS_PROXY 무시 (모듈 docstring 참고)
    s.headers.update(HEADERS)
    return s


def _get(sess: requests.Session, url: str, delay: float) -> str:
    r = sess.get(url, timeout=25)
    r.raise_for_status()
    time.sleep(delay)
    return r.text


# ── 파서 ─────────────────────────────────────────────────────────────────
def parse_listing(html: str) -> list[dict]:
    """목록 HTML → search_data.events.results 원본 dict 리스트. JSON이 없으면 빈 리스트."""
    m = SERVER_DATA_RE.search(html)
    if not m:
        return []
    events = (json.loads(m.group(1)).get("search_data") or {}).get("events") or {}
    return [r for r in events.get("results") or [] if isinstance(r, dict)]


def _listing_text(res: dict) -> str:
    tags = " ".join((t.get("display_name") or "") for t in res.get("tags") or []
                    if isinstance(t, dict) and t.get("display_name") not in FORMAT_TAGS_IGNORED)
    return f"{res.get('summary') or ''}\n{tags}"


def parse_detail(html: str) -> dict:
    """상세 HTML → {host, body, availability_ends}.

    본문은 텍스트 모듈만 모아 태그를 벗긴다. 모듈이 하나도 없는 페이지(요약만 쓴 공고)는
    basicInfo.summary 가 본문이다.
    """
    m = NEXT_DATA_RE.search(html)
    if not m:
        return {}
    ctx = ((json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}).get("context") or {}
    modules = (ctx.get("structuredContent") or {}).get("modules") or []
    raw = "\n".join(mod.get("text") or "" for mod in modules if mod.get("type") == "text")
    info = ctx.get("basicInfo") or {}
    body = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True) or \
        (info.get("summary") or "").strip()
    body = re.sub(r"[ \t\xa0]+", " ", body)
    offers = (ctx.get("seo") or {}).get("offersSchema") or []
    return {
        "host": ((info.get("organizer") or {}).get("name") or "").strip(),
        "body": body,
        "availability_ends": offers[0].get("availabilityEnds") if offers else None,
    }


def result_to_item(res: dict, detail: dict | None) -> dict:
    """목록 result + 상세(parse_detail 결과, 없으면 None) → 공통 스키마 dict."""
    detail = detail or {}
    eid = res.get("eventbrite_event_id") or res.get("id")
    title = (res.get("name") or "").strip()
    url = res.get("url") or ""
    summary = (res.get("summary") or "").strip()

    venue = res.get("primary_venue") or {}
    if res.get("is_online_event"):
        location = "Online"
    else:
        location = ((venue.get("address") or {}).get("localized_address_display")
                    or venue.get("name") or "Hong Kong")

    start = f"{res.get('start_date') or ''} {res.get('start_time') or ''}".strip()
    end = f"{res.get('end_date') or ''} {res.get('end_time') or ''}".strip()
    period = f"{start} ~ {end}" if start and end else start

    body = detail.get("body") or ""
    if not body:
        log.warning("Eventbrite 본문 없음: %s", url)
        body = summary or title
    elif summary and summary != title and summary not in body:
        body = f"{summary}\n{body}"        # 목록 요약이 본문에 없으면 앞에 붙인다
    m = re.search(r"(?i)\bopen to\b[^.\n]*", body)

    tags = [t.get("display_name") for t in res.get("tags") or []
            if isinstance(t, dict) and t.get("display_name")]
    return {
        "source": "Eventbrite 홍콩(홍콩)",
        "ix": f"eventbrite-{eid}",
        "url": url,
        "homepage": url,
        "title": title,
        "field": ", ".join(tags[:4]) or "이벤트",
        "target": m.group(0).strip() if m else "확인필요 (본문에 대상 미기재)",
        "host": detail.get("host") or "",
        "period": period,
        "prize": _prize_lines(body),
        # 티켓 판매 종료(UTC→HKT 날짜)를 마감으로, 없으면 행사 시작일(현지 날짜)
        "deadline": iso_to_hk_date(detail.get("availability_ends")) or res.get("start_date"),
        "body": body[:BODY_MAX],
        "lang": "en",
        "location": location,
    }


def scrape(pages: int = 3, max_details: int = 20, delay: float = 1.0) -> list[dict]:
    """Eventbrite 홍콩 → 대회성 이벤트만 공통 스키마 dict 리스트."""
    sess = _session()
    cands, seen = [], set()
    for kw in LIST_KEYWORDS:
        for page in range(1, pages + 1):
            url = f"{BASE}/d/hong-kong-sar/{kw}/?page={page}"
            try:
                results = parse_listing(_get(sess, url, delay))
            except Exception as e:
                log.warning("Eventbrite 목록 실패 %s: %s", url, e)
                break
            if not results:
                break
            for res in results:
                eid = res.get("eventbrite_event_id") or res.get("id")
                if not eid or eid in seen:
                    continue
                seen.add(eid)
                if is_competition_text(res.get("name") or "", _listing_text(res)):
                    cands.append(res)
    log.info("Eventbrite 홍콩 목록: %d건 중 대회 후보 %d건", len(seen), len(cands))

    items = []
    for res in cands[:max_details]:
        try:
            detail = parse_detail(_get(sess, res["url"], delay))
        except Exception as e:
            log.warning("Eventbrite 상세 실패 %s: %s", res.get("url"), e)
            detail = None
        items.append(result_to_item(res, detail))
    log.info("Eventbrite 홍콩: %d건", len(items))
    return items
