# -*- coding: utf-8 -*-
"""홍콩 개발자 커뮤니티 해커톤 수집 — 작은 공개 피드 셋을 소스 하나로 합친다.

  DoraHacks        https://dorahacks.io/api/v1/hub/hackathons  (JSON, 인증 없음)
      전 세계 해커톤 목록. 서버 쪽 지역 파라미터는 무시되므로 upcoming/ongoing 페이지와
      'Hong Kong' 검색 결과를 받아 클라이언트에서 홍콩 건만 남긴다
      (venue_city_id 1344982653 = 홍콩, venue_country_id 92, 또는 제목/장소에 hong kong·hk).
  GDG Hong Kong    https://gdg.community.dev/api/event_slim/for_chapter/660/  (Bevy JSON)
      챕터 이벤트. 스터디잼·토크가 대부분이라 제목+본문 키워드로 해커톤만 남긴다.
      정식 URL은 /api/event/?chapter=660 에서 id로 맞춘다(없으면 static_url).
  AI Tinkerers HK  https://hong-kong.aitinkerers.org/  (홈 ld+json의 schema.org Event)
      /events 는 Cloudflare 차단이라 홈만 읽는다. 목록의 description은 200자 요약이라
      상세(/p/<slug>)의 article.prose 본문을 max_details 건까지 읽는다.

세 피드 모두 대회가 아닌 모임이 섞여 있으므로 제목+본문이 COMPETITION_RE에 걸린 건만 남기고,
종료일(없으면 시작일)이 오늘(홍콩 날짜) 이전인 건은 버린다.

프록시: hkust.py와 같은 이유로 환경변수 프록시를 무시하는 세션을 쓴다.
"""
import re
import json
import time
import logging
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from scraper.hkust import HEADERS, HKT, BODY_MAX, iso_to_hk_date, deadline_from_body
from scraper.unstop import _clean_html

log = logging.getLogger("hk_devcomm")

SOURCE = "홍콩 개발자커뮤니티(홍콩)"

DORA_API = "https://dorahacks.io/api/v1/hub/hackathons"
DORA_QUERIES = [{"page": 1, "page_size": 50, "status": "upcoming"},
                {"page": 1, "page_size": 50, "status": "ongoing"},
                {"page": 1, "page_size": 50, "search": "Hong Kong"}]
DORA_HK_CITY, DORA_HK_COUNTRY = 1344982653, 92

GDG_SLIM = "https://gdg.community.dev/api/event_slim/for_chapter/660/?page_size=20&status=Live"
GDG_FULL = "https://gdg.community.dev/api/event/?chapter=660&status=Live"

AIT_BASE = "https://hong-kong.aitinkerers.org"

# hkust.COMPETITION_WORDS 보다 좁다: awards/prizes/cup 은 모임 소개문에도 흔해서 뺐다.
# 'no-pitch networking'(AI Tinkerers 상투구)이 pitch 에 걸리지 않게 lookbehind 를 둔다.
COMPETITION_RE = re.compile(
    r"(?i)\b(hackathon|hackerhouse|competition|challenge|contest|ideathon|datathon"
    r"|jam|olympiad|(?<!no-)pitch)\b")
_HK_RE = re.compile(r"(?i)\bhong\s*kong\b|\bhk\b")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False          # HTTPS_PROXY 무시
    s.headers.update(HEADERS)
    return s


def _get(sess: requests.Session, url: str, delay: float = 1.0, **kw) -> requests.Response:
    r = sess.get(url, timeout=25, **kw)
    r.raise_for_status()
    time.sleep(delay)
    return r


def is_competition_text(title: str, body: str) -> bool:
    return bool(COMPETITION_RE.search(f"{title}\n{body}"))


def _ts_to_hk_date(ts) -> str | None:
    """unix 초 → 홍콩 날짜 'YYYY-MM-DD'."""
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), HKT).strftime("%Y-%m-%d")


def _period(start: str | None, end: str | None) -> str:
    if start and end and start != end:
        return f"{start} ~ {end}"
    return start or end or ""


def _is_over(start: str | None, end: str | None, today: date) -> bool:
    """종료일(없으면 시작일)이 오늘 이전이면 True. 날짜가 아예 없으면 남긴다."""
    last = end or start
    return bool(last) and last < today.isoformat()


# ── DoraHacks ─────────────────────────────────────────────────────────────
def _dora_is_hk(h: dict) -> bool:
    if h.get("venue_city_id") == DORA_HK_CITY or h.get("venue_country_id") == DORA_HK_COUNTRY:
        return True
    text = " ".join(str(h.get(k) or "") for k in ("title", "venue_name", "venue_address"))
    return bool(_HK_RE.search(text))


def dorahacks_items(json_obj: dict, today: date) -> list[dict]:
    """hub/hackathons 응답 → 홍콩 해커톤만 공통 스키마로."""
    items = []
    for h in json_obj.get("results") or []:
        if not _dora_is_hk(h):
            continue
        start, end = _ts_to_hk_date(h.get("timeline_start")), _ts_to_hk_date(h.get("timeline_end"))
        if _is_over(start, end, today):
            continue
        title = (h.get("title") or "").strip()
        uname = h.get("uname") or str(h.get("id"))
        url = f"https://dorahacks.io/hackathon/{uname}"
        pre = _ts_to_hk_date(h.get("timeline_pre_register"))
        # 사전등록 마감이 앞에 있으면 그것, 아니면 시작일, 이미 진행 중이면 종료일(제출 마감)
        deadline = next((d for d in (pre, start, end) if d and d >= today.isoformat()), None)
        host = (h.get("owner") or {}).get("name") or h.get("ecosystem") or "DoraHacks"
        prize = f"{h['bonus_price']} {h.get('bonus_token') or ''}".strip() if h.get("bonus_price") else ""
        venue = ", ".join(v for v in (h.get("venue_name"), h.get("venue_address")) if v)
        location = f"Hong Kong ({venue})" if venue else \
            ("Online" if h.get("venue_form") == "Virtual" else "Hong Kong")
        desc = _clean_html(h.get("desc") or h.get("description") or "")
        body = (f"{title}\n[Organizer] {host}\n[Format] {h.get('venue_form') or ''} {venue}\n"
                f"[Period] {_period(start, end)}\n[Tags] {h.get('tags') or ''} / {h.get('ecosystem') or ''}\n"
                f"[Prize] {prize or 'not specified'}\n{desc}")
        if not is_competition_text(title, body):
            continue
        items.append({
            "source": SOURCE, "ix": f"dorahacks-{uname}", "url": url, "homepage": url,
            "title": title, "field": f"해커톤 ({h.get('tags') or 'Web3'})",
            "target": "확인필요 (DoraHacks 목록에 대상 미기재)", "host": host,
            "period": _period(start, end), "prize": prize, "deadline": deadline,
            "body": body[:BODY_MAX], "lang": "en", "location": location,
        })
    return items


# ── GDG Hong Kong ─────────────────────────────────────────────────────────
def gdg_items(json_obj: dict, today: date, urls: dict | None = None) -> list[dict]:
    """event_slim 응답 → 대회성 이벤트만 공통 스키마로. urls={id: 정식 URL} (선택)."""
    items = []
    for ev in json_obj.get("results") or []:
        start, end = iso_to_hk_date(ev.get("start_date")), iso_to_hk_date(ev.get("end_date"))
        if _is_over(start, end, today):
            continue
        title = (ev.get("title") or "").strip()
        body = _clean_html(ev.get("description") or "") or (ev.get("description_short") or "")
        if not is_competition_text(title, body):
            log.info("GDG 대회 아님 건너뜀: %s", title)
            continue
        eid = ev.get("id")
        url = (urls or {}).get(eid) or ev.get("static_url") or f"https://gdg.community.dev/e/{eid}/"
        online = ev.get("audience_type") == "VIRTUAL" or ev.get("is_virtual_event")
        items.append({
            "source": SOURCE, "ix": f"gdg-hk-{eid}", "url": url, "homepage": url,
            "title": title, "field": "해커톤·개발자 커뮤니티",
            "target": "확인필요 (본문 참고)", "host": "GDG Hong Kong",
            "period": _period(start, end), "prize": "",
            # 접수 마감이 본문에 연도 포함으로 적혀 있으면 그것, 아니면 행사 시작일
            "deadline": deadline_from_body(body) or start,
            "body": body[:BODY_MAX], "lang": "en",
            "location": "Online" if online else "Hong Kong (in person)",
        })
    return items


# ── AI Tinkerers Hong Kong ────────────────────────────────────────────────
def _ld_json_blocks(html: str) -> list[dict]:
    out = []
    for sc in BeautifulSoup(html, "html.parser").find_all("script", type="application/ld+json"):
        try:
            out.append(json.loads(sc.string or sc.get_text()))
        except (ValueError, TypeError):
            continue
    return out


def aitinkerers_events(html: str) -> list[dict]:
    """홈 HTML의 모든 ld+json ItemList 에서 schema.org Event 를 모은다 (url 기준 중복 제거).

    '#events' 목록이 본 목록이지만, 첫 ItemList(@id 없음)에만 있는 해커톤이 실측되어
    전체를 합친다.
    """
    seen, events = set(), []
    for d in _ld_json_blocks(html):
        if d.get("@type") != "ItemList":
            continue
        for li in d.get("itemListElement") or []:
            it = li.get("item") or {}
            if it.get("@type") != "Event":
                continue
            url = it.get("url") or li.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            events.append(it)
    return events


def aitinkerers_detail_body(html: str) -> str:
    """상세 페이지 → 본문. article.prose 를 우선, 없으면 Event ld+json description."""
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("article.prose") or soup.select_one(".show-page-body")
    if node is not None:
        text = re.sub(r"[ \t\xa0]+", " ", node.get_text("\n", strip=True))
        if text:
            return text[:BODY_MAX]
    for d in _ld_json_blocks(html):
        if d.get("@type") == "Event" and d.get("description"):
            return d["description"][:BODY_MAX]
    return ""


def aitinkerers_items(html: str, today: date, fetch=None) -> list[dict]:
    """홈 HTML → 대회성 이벤트만 공통 스키마로.

    fetch(url) -> html 을 주면 날짜가 지나지 않은 이벤트의 상세 본문을 읽는다(호출 수 제한은
    호출자가 fetch 안에서 건다). 없으면 목록의 요약 description 으로 판정한다.
    """
    items = []
    for ev in aitinkerers_events(html):
        if "cancel" in (ev.get("eventStatus") or "").lower():
            continue
        start, end = iso_to_hk_date(ev.get("startDate")), iso_to_hk_date(ev.get("endDate"))
        if _is_over(start, end, today):
            continue
        title = (ev.get("name") or "").strip()
        url = ev.get("url") or ""
        body = ""
        if fetch is not None:
            try:
                detail = fetch(url)
                body = aitinkerers_detail_body(detail) if detail else ""
            except Exception as e:  # noqa: BLE001
                log.warning("AI Tinkerers 상세 실패 %s: %s", url, e)
        body = body or (ev.get("description") or "")
        if not is_competition_text(title, body):
            log.info("AI Tinkerers 대회 아님 건너뜀: %s", title)
            continue
        loc = ev.get("location") or {}
        online = "online" in (ev.get("eventAttendanceMode") or "").lower()
        venue = ", ".join(v for v in (loc.get("name"), (loc.get("address") or {}).get("addressLocality"))
                          if v and v != "Private venue")
        offers = ev.get("offers") or {}
        fee = offers.get("price")
        items.append({
            "source": SOURCE, "ix": "aitinkerers-hk-" + url.rstrip("/").rsplit("/", 1)[-1],
            "url": url, "homepage": url, "title": title, "field": "AI 해커톤",
            "target": "확인필요 (본문 참고)", "host": "AI Tinkerers Hong Kong",
            "period": _period(start, end), "prize": "",
            "deadline": deadline_from_body(body) or start,
            "body": (f"{title}\n[Fee] {fee if fee is not None else 'not specified'}\n{body}")[:BODY_MAX],
            "lang": "en",
            "location": "Online" if online else f"Hong Kong ({venue})" if venue else "Hong Kong (in person)",
        })
    return items


# ── 진입점 ─────────────────────────────────────────────────────────────────
def scrape(pages: int = 1, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """세 피드를 합쳐 공통 스키마 dict 리스트로. 피드 하나가 죽어도 나머지는 낸다."""
    sess = _session()
    today = datetime.now(HKT).date()
    items, seen = [], set()

    def _add(new: list[dict], label: str):
        n = 0
        for it in new:
            if it["ix"] not in seen:
                seen.add(it["ix"])
                items.append(it)
                n += 1
        log.info("%s: %d건", label, n)

    # 1) DoraHacks
    dora = []
    for q in DORA_QUERIES:
        for page in range(1, pages + 1):
            try:
                data = _get(sess, DORA_API, delay, params={**q, "page": page}).json()
            except Exception as e:
                log.warning("DoraHacks 실패 %s: %s", q, e)
                break
            dora.extend(dorahacks_items(data, today))
            if not data.get("next"):
                break
    _add(dora, "DoraHacks 홍콩")

    # 2) GDG Hong Kong
    try:
        slim = _get(sess, GDG_SLIM, delay).json()
        urls = {}
        try:
            urls = {e.get("id"): e.get("url")
                    for e in _get(sess, GDG_FULL, delay).json().get("results") or [] if e.get("url")}
        except Exception as e:
            log.warning("GDG 정식 URL 조회 실패(static_url 사용): %s", e)
        _add(gdg_items(slim, today, urls), "GDG Hong Kong")
    except Exception as e:
        log.warning("GDG 실패: %s", e)

    # 3) AI Tinkerers Hong Kong
    budget = {"left": max_details}

    def _fetch(url: str) -> str:
        if budget["left"] <= 0 or not url.startswith(AIT_BASE + "/p/"):
            return ""
        budget["left"] -= 1
        return _get(sess, url, delay).text

    try:
        html = _get(sess, AIT_BASE + "/", delay).text
        _add(aitinkerers_items(html, today, _fetch), "AI Tinkerers HK")
    except Exception as e:
        log.warning("AI Tinkerers 실패: %s", e)

    log.info("홍콩 개발자커뮤니티 합계: %d건", len(items))
    return items
