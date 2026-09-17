# -*- coding: utf-8 -*-
"""Luma(luma.com) 홍콩 이벤트 중 해커톤·대회 수집 — 공개 JSON API 사용.

HTML 페이지(luma.com/hongkong)는 Vercel 방화벽이 브라우저 헤더 전체를 요구해 불안정하고,
공개 API(api.lu.ma)는 인증 없이 UA + Accept 헤더만으로 200이다(2026-09-13 실측).

  GET /discover/get-place?slug=hongkong                 → place.api_id
  GET /discover/get-paginated-events
        ?discover_place_api_id=<id>&pagination_limit=50&query=<단어>
      query 없이 부르면 큐레이션 ~10건만 온다. 키워드별로 한 번씩 부르고
      event.api_id 로 중복을 제거한다. 목록엔 본문이 없다.
  GET /event/get?event_api_id=<id>
      description_mirror(ProseMirror JSON) 가 본문, ticket_types[].valid_end_at 이 등록 마감.

프록시: hkust 모듈과 같은 이유로 환경변수 프록시(HTTPS_PROXY)를 무시하는 세션을 쓴다.
"""
import re
import time
import logging
from datetime import datetime, timezone

import requests

from scraper.hkust import HKT, iso_to_hk_date, _prize_lines

log = logging.getLogger("luma")

API = "https://api.lu.ma"
PLACE_SLUG = "hongkong"
PLACE_ID_FALLBACK = "discplace-z9B5Guglh2WINA1"   # 2026-09-13 실측값. 런타임 조회 실패 시 사용
QUERIES = ["hackathon", "competition", "challenge", "contest",
           "pitch", "ideathon", "datathon"]
PAGE_LIMIT = 50

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
BODY_MAX = 8000

# hkust.COMPETITION_WORDS 보다 좁다(award/prize/cup 제외). 밋업이 대부분인 Luma에 맞춘 것.
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


def _get_json(sess: requests.Session, path: str, params: dict, delay: float) -> dict:
    r = sess.get(f"{API}{path}", params=params, timeout=25)
    r.raise_for_status()
    time.sleep(delay)
    return r.json()


# ── 본문(ProseMirror) ────────────────────────────────────────────────────
def flatten_prosemirror(doc) -> str:
    """TipTap/ProseMirror 문서 → 평문. 최상위 블록마다 줄바꿈, hard_break 도 줄바꿈."""
    def _text(node) -> str:
        if isinstance(node, list):
            return "".join(_text(n) for n in node)
        if not isinstance(node, dict):
            return ""
        if node.get("type") == "hard_break":
            return "\n"
        if node.get("type") == "text":
            return node.get("text") or ""
        return _text(node.get("content") or [])

    if not isinstance(doc, dict):
        return ""
    text = "\n".join(_text(block) for block in doc.get("content") or [])
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


# ── API ──────────────────────────────────────────────────────────────────
def _place_id(sess: requests.Session, delay: float) -> str:
    try:
        pid = (_get_json(sess, "/discover/get-place", {"slug": PLACE_SLUG}, delay)
               .get("place") or {}).get("api_id")
    except Exception as e:
        log.warning("Luma place 조회 실패, 기본값 사용: %s", e)
        pid = None
    return pid or PLACE_ID_FALLBACK


def _list_entries(sess: requests.Session, place_id: str, pages: int, delay: float) -> list[dict]:
    """키워드별 목록 호출 → event.api_id 기준 중복 제거한 entry 리스트."""
    entries, seen = [], set()
    for q in QUERIES:
        cursor = None
        for _ in range(max(1, pages)):
            params = {"discover_place_api_id": place_id,
                      "pagination_limit": PAGE_LIMIT, "query": q}
            if cursor:
                params["pagination_cursor"] = cursor
            try:
                data = _get_json(sess, "/discover/get-paginated-events", params, delay)
            except Exception as e:
                log.warning("Luma 목록 실패 query=%s: %s", q, e)
                break
            for ent in data.get("entries") or []:
                aid = (ent.get("event") or {}).get("api_id")
                if aid and aid not in seen:
                    seen.add(aid)
                    entries.append(ent)
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
    return entries


def _hk_stamp(iso: str | None) -> str:
    """'2026-10-03T01:00:00.000Z' → '2026-10-03 09:00' (HKT)."""
    d = iso_to_hk_date(iso)
    if not d:
        return ""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(HKT).strftime("%Y-%m-%d %H:%M")


def entry_to_item(entry: dict, detail: dict | None) -> dict:
    """목록 entry + 상세(/event/get 응답, 없으면 None) → 공통 스키마 dict."""
    ev = entry.get("event") or {}
    detail = detail or {}
    title = (ev.get("name") or "").strip()
    slug = ev.get("url") or ev.get("api_id")
    url = f"https://luma.com/{slug}"

    hosts = entry.get("hosts") or detail.get("hosts") or []
    host = (hosts[0].get("name") if hosts else "") or \
        ((entry.get("calendar") or detail.get("calendar") or {}).get("name") or "")

    geo = ev.get("geo_address_info") or {}
    if ev.get("location_type") == "online":
        location = "Online"
    else:
        location = geo.get("full_address") or geo.get("address") or geo.get("city_state") or "Hong Kong"

    start, end = _hk_stamp(ev.get("start_at")), _hk_stamp(ev.get("end_at"))
    period = f"{start} ~ {end} (HKT)" if start and end else start

    # 등록 마감 = 티켓 판매 종료(valid_end_at) 중 가장 이른 것. 없으면 행사 시작일
    # (Luma는 보통 행사 시작과 함께 등록이 닫힌다).
    ends = sorted(t.get("valid_end_at") for t in detail.get("ticket_types") or []
                  if t.get("valid_end_at"))
    deadline = iso_to_hk_date(ends[0]) if ends else iso_to_hk_date(ev.get("start_at"))

    body = flatten_prosemirror(detail.get("description_mirror"))
    if not body:
        log.warning("Luma 본문 없음: %s", url)
        body = f"{title} | host: {host} | when: {period} | where: {location}"
    m = re.search(r"(?i)\bopen to\b[^.\n]*", body)

    cats = ", ".join((c.get("name") or "") for c in detail.get("categories") or [] if c.get("name"))
    return {
        "source": "Luma 홍콩(홍콩)",
        "ix": f"luma-{ev.get('api_id')}",
        "url": url,
        "homepage": url,
        "title": title,
        "field": cats or "이벤트",
        "target": m.group(0).strip() if m else "확인필요 (본문에 대상 미기재)",
        "host": host,
        "period": period,
        "prize": _prize_lines(body),
        "deadline": deadline,
        "body": body[:BODY_MAX],
        "lang": "en",
        "location": location,
    }


def scrape(pages: int = 1, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """Luma 홍콩 → 대회성 이벤트만 공통 스키마 dict 리스트."""
    sess = _session()
    place_id = _place_id(sess, delay)
    entries = _list_entries(sess, place_id, pages, delay)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    upcoming = [e for e in entries if ((e.get("event") or {}).get("start_at") or "")[:19] >= now]
    log.info("Luma 홍콩 목록: %d건 (예정 %d건)", len(entries), len(upcoming))

    # 목록엔 본문이 없어 제목만으로 1차 선별하고, 상세 예산(max_details)은 제목 매칭 건부터 쓴다.
    upcoming.sort(key=lambda e: not is_competition_text((e.get("event") or {}).get("name") or "", ""))
    items = []
    for ent in upcoming[:max_details]:
        aid = ent["event"]["api_id"]
        try:
            detail = _get_json(sess, "/event/get", {"event_api_id": aid}, delay)
        except Exception as e:
            log.warning("Luma 상세 실패 %s: %s", aid, e)
            detail = None
        it = entry_to_item(ent, detail)
        if not is_competition_text(it["title"], it["body"]):
            log.info("대회 아님 건너뜀: %s", it["title"])
            continue
        items.append(it)
    log.info("Luma 홍콩: %d건", len(items))
    return items
