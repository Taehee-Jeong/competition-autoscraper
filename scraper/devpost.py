# -*- coding: utf-8 -*-
"""Devpost(devpost.com) 해외 해커톤 수집 — 공개 JSON API 사용.

  https://devpost.com/api/hackathons?page=N&open_state=open
인증 불필요. HTML 파싱이 아니라 API라서 사이트 디자인 변경에 안정적.
응답 필드는 방어적으로 접근한다 (필드가 빠져도 죽지 않게).
"""
import re
import time
import html
import logging
import requests
from datetime import date

log = logging.getLogger("devpost")

API = "https://devpost.com/api/hackathons"
# Devpost는 단순 UA면 403을 준다. 실제 브라우저 XHR과 동일한 헤더 세트를 보낸다.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://devpost.com/hackathons",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _parse_end_date(period: str) -> str | None:
    """'Jul 21 - Aug 25, 2026' / 'Aug 25, 2026' / 'Sep 18 - 19, 2026' → 종료일 'YYYY-MM-DD'.

    같은 달 안의 기간은 'Sep 18 - 19, 2026'처럼 뒤쪽에 월이 없다. 그때는 앞쪽 월을 쓴다
    (2026-09 전까지는 None이 나와 마감 판정이 '확인필요'로 빠졌다).
    """
    if not period:
        return None
    period = period.strip()
    m = re.search(r"([A-Z][a-z]{2})[a-z]*\s+(\d{1,2}),?\s+(\d{4})\s*$", period)
    if not m:
        m = re.search(r"^([A-Z][a-z]{2})[a-z]*\s+\d{1,2}\s*[-–]\s*(\d{1,2}),?\s+(\d{4})\s*$", period)
    if not m:
        return None
    mon = MONTHS.get(m.group(1))
    if not mon:
        return None
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def scrape(pages: int = 2, delay: float = 1.0, search: str | None = None,
           source: str = "Devpost(해외)") -> list[dict]:
    """접수중(open) 해커톤을 최신순으로 수집 → 공통 스키마 dict 리스트.

    search를 주면 Devpost 검색 결과를 받는다. 검색 모드에서는 API가 open_state를
    무시하고 2014년 대회까지 섞어 주므로(2026-09 실측) 마감이 지난 건은 여기서 버린다.
    """
    items: list[dict] = []
    today = date.today().isoformat()
    for page in range(1, pages + 1):
        params = {"page": page, "open_state": "open", "order_by": "recently-added"}
        if search:
            params["search"] = search
        try:
            r = requests.get(API, headers=HEADERS, timeout=20, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("Devpost API 실패 page=%d: %s", page, e)
            break
        hackathons = data.get("hackathons") or []
        if not hackathons:
            break
        for h in hackathons:
            period = h.get("submission_period_dates", "") or ""
            themes = ", ".join(t.get("name", "") for t in (h.get("themes") or []))
            loc = (h.get("displayed_location") or {}).get("location", "")
            prize = _strip_html(str(h.get("prize_amount", "")))
            deadline = _parse_end_date(period)
            if search and (deadline is None or deadline < today):
                continue
            items.append({
                "source": source,
                "ix": f"devpost-{h.get('id', h.get('url', ''))}",
                "url": h.get("url", ""),
                "homepage": h.get("url", ""),
                "title": _strip_html(h.get("title", "")),
                "field": f"해커톤 / {themes}" if themes else "해커톤",
                "target": "Devpost 참가자 (상세 공고 확인)",
                "host": h.get("organization_name", "") or "Devpost 주최사",
                "period": period,
                "prize": prize,
                "deadline": deadline,
                "location": loc,
                # Devpost API는 자격 전문을 안 주므로 본문은 요약 정보로 구성
                "body": f"{h.get('title','')} | location: {loc} | "
                        f"themes: {themes} | submission: {period} | "
                        f"registrations: {h.get('registrations_count','?')}",
                "lang": "en",
            })
        log.info("Devpost %d페이지: 누적 %d건", page, len(items))
        time.sleep(delay)
    return items
