# -*- coding: utf-8 -*-
"""홍콩 정부 청년포털(youth.gov.hk) 대회 수집 — Statamic 공개 JSON API.

  https://www.youth.gov.hk/api/collections/events/entries
      ?limit=100&filter[title:contains]=Competition

전체 이벤트가 2,369건(3개 언어)이라 통째로 받지 않고, 제목 검색어별로 조회한 뒤
영문(locale=default)·마감 미경과 건만 남긴다. 2026-09-13 실측:
  - filter[title:contains]=… 는 URL 인코딩(%5B %5D %3A)해야 WAF를 통과한다.
    filter[locale:is], filter[application_deadline:gte]는 인코딩해도 "Request Rejected".
  - limit=500은 50초·4MB, limit=1000은 타임아웃. 100이 적당.
  - 목록의 상당수가 지역 구민 스포츠 대회·수상작 순회전시·시상식이라 제목으로 거른다.

이 서버 셸의 HTTPS_PROXY를 타면 홍콩 사이트가 간헐적으로 끊겨 프록시를 우회한다(hkust.py와 동일).
"""
import re
import html
import time
import logging
from datetime import date, datetime, timedelta, timezone

import requests

log = logging.getLogger("youthgov")

BASE = "https://www.youth.gov.hk"
API = f"{BASE}/api/collections/events/entries"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}
QUERY_WORDS = ["Competition", "Contest", "Hackathon", "Challenge", "Award"]
HKT = timezone(timedelta(hours=8))
BODY_MAX = 8000

# 대학생 공지에 안 맞는 것: 수상작 전시·시상식, 지역 구민 스포츠 리그
EXCLUDE_TITLE = re.compile(
    r"(?i)\b(exhibition|ceremony|badminton|football|soccer|fu[st]sal|basketball|volleyball|"
    r"tennis|archery|lawn\s*bowls|gateball|athletic|swimming|gymnastics|marathon|"
    r"tug[- ]of[- ]war|dance\s+competition|age\s+group|singing|karaoke|colou?ring)\b")

TAG_RE = re.compile(r"<[^>]+>")


def _clean(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):                       # content가 블록 리스트로 오는 형식
        raw = "\n".join(b.get("text", "") for b in raw if isinstance(b, dict))
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(raw))
    text = html.unescape(TAG_RE.sub(" ", text))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _hk_date(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(HKT).strftime("%Y-%m-%d")


def _external_link(entry: dict) -> str:
    link = entry.get("link") or {}
    if not isinstance(link, dict):
        return ""
    for key in ("online_application_webpage", "related_webpage", "application_form_download"):
        v = link.get(key)
        if isinstance(v, list) and v:
            return str(v[0])
        if isinstance(v, str) and v:
            return v
    return ""


def is_wanted(entry: dict, today: date | None = None) -> bool:
    """영문 + 마감 미경과(또는 마감 미기재) + 제외어 없음."""
    today = today or date.today()
    if entry.get("locale") != "default":
        return False
    if entry.get("published") is False:
        return False
    if EXCLUDE_TITLE.search(entry.get("title") or ""):
        return False
    dl = _hk_date(entry.get("application_deadline"))
    return dl is None or dl >= today.isoformat()


def to_item(entry: dict) -> dict:
    title = (entry.get("title") or "").strip()
    url = entry.get("permalink") or (BASE + entry.get("url", ""))
    body = _clean(entry.get("content"))
    extra = []
    for key in ("application_method", "remarks", "free_text"):
        v = _clean(entry.get(key))
        if v:
            extra.append(v)
    if extra:
        body = (body + "\n" + "\n".join(extra)).strip()
    venue = (entry.get("venue") or {}).get("address", "") if isinstance(entry.get("venue"), dict) else ""
    cats = ", ".join(c.get("title", "") for c in (entry.get("categories") or []) if isinstance(c, dict))
    start, end = _hk_date(entry.get("start_date")), _hk_date(entry.get("end_date"))
    period = f"{start} ~ {end}" if start and end and start != end else (start or "")
    fee = _clean(entry.get("fee"))
    return {
        "source": "Youth.gov.hk(홍콩)",
        "ix": f"youthgov-{entry.get('id', '')}",
        "url": url,
        "homepage": _external_link(entry) or url,
        "title": title,
        "field": cats or "홍콩 청년포털",
        "target": "확인필요 (본문 참고)",
        "host": _clean(entry.get("organize")) or "",
        "period": period,
        "prize": "",
        "deadline": _hk_date(entry.get("application_deadline")),
        "body": (body or f"{title} | {cats} | venue: {venue}")[:BODY_MAX],
        "lang": "en",
        "location": venue or "홍콩",
        "fee": fee[:80] if fee else None,
    }


def scrape(max_details: int = 60, delay: float = 1.0,
           today: date | None = None) -> list[dict]:
    """검색어별 조회 → 영문·미마감·대회성 건만 → 공통 스키마 dict 리스트."""
    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update(HEADERS)
    seen, items = set(), []
    for word in QUERY_WORDS:
        url = f"{API}?limit=100&filter%5Btitle%3Acontains%5D={word}"
        try:
            r = sess.get(url, timeout=60)
            r.raise_for_status()
            data = r.json().get("data") or []
        except Exception as e:
            log.warning("youth.gov.hk 조회 실패 (%s): %s", word, e)
            continue
        kept = 0
        for entry in data:
            eid = entry.get("id")
            if eid in seen or not is_wanted(entry, today):
                continue
            seen.add(eid)
            items.append(to_item(entry))
            kept += 1
        log.info("youth.gov.hk '%s': %d건 중 %d건 채택", word, len(data), kept)
        time.sleep(delay)
    items = items[:max_details]
    log.info("youth.gov.hk: %d건", len(items))
    return items
