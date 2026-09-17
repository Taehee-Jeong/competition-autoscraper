# -*- coding: utf-8 -*-
"""언스탑(unstop.com) 해외 공모전/해커톤 수집 — 공개 JSON API 사용.

  https://unstop.com/api/public/opportunity/search-new
      ?opportunity={competitions|hackathons}&page=N&per_page=15&oppstatus=open

robots.txt에서 `Allow: /api/public/*` 로 명시 허용된 경로다(2026-07 실측).
인증·쿠키·API키 불필요하고 브라우저 User-Agent 헤더 하나만 있으면 200이다
(UA를 아예 안 보내면 403).

상세 페이지(seo_url)는 Angular SPA 쉘이라 JS 없이는 본문이 나오지 않고
(가시 텍스트 104자), 상세용 public API도 404다. 따라서 본문까지 목록 API
응답의 `details` 필드 하나로 끝낸다. 이 필드는 공고 본문 HTML 원문이라
네비게이션·사이드바·푸터가 애초에 섞이지 않는다.
"""
import re
import time
import html
import logging
import requests

log = logging.getLogger("unstop")

API = "https://unstop.com/api/public/opportunity/search-new"
# UA가 유일한 필수 헤더. Accept는 예의상 붙인다.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}

# 수집 대상 카테고리 (동일 스키마)
OPPORTUNITIES = ["competitions", "hackathons"]
PER_PAGE = 15

# prizes[].currency 는 폰트 아이콘 클래스명으로 온다
CURRENCY = {"fa-rupee": "INR", "fa-dollar": "USD", "fa-euro": "EUR",
            "fa-gbp": "GBP", "fa-yen": "JPY"}

BODY_MAX = 8000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 본문 정제용: 블록 태그는 줄바꿈으로 살리고 나머지 태그만 제거한다
SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
BLOCK_RE = re.compile(r"</?(p|li|div|br|h[1-6]|tr|ul|ol|table)[^>]*>", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(raw: str) -> str:
    """공고 본문 HTML 조각 → 평문. 실패하면 빈 문자열."""
    if not raw:
        return ""
    text = SCRIPT_RE.sub(" ", raw)
    text = BLOCK_RE.sub("\n", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n", text)
    return text.strip()


def _iso_date(s: str | None) -> str | None:
    """'2026-08-07T00:00:00+05:30' → '2026-08-07'. 형식이 다르면 None."""
    if not s or not isinstance(s, str):
        return None
    head = s[:10]
    return head if DATE_RE.match(head) else None


def _prize_text(prizes: list) -> str:
    """cash가 있는 항목만 '순위: 통화 금액' 으로 합친다."""
    parts = []
    for p in prizes or []:
        if not isinstance(p, dict):
            continue
        cash = p.get("cash")
        if not cash:
            continue
        cur = p.get("currencyCode") or CURRENCY.get(p.get("currency") or "", "")
        rank = (p.get("rank") or "").strip() or "Prize"
        parts.append(f"{rank}: {cur} {cash}".replace("  ", " ").strip())
    return " / ".join(parts)


def _team_line(regn: dict) -> str:
    """팀 참가 가능 여부는 본문 문장이 아니라 구조화 필드에만 있다."""
    mn, mx = regn.get("min_team_size"), regn.get("max_team_size")
    if isinstance(mx, int) and mx >= 2:
        return f"Teams of {mn or 1} to {mx} members"
    if mx == 1:
        return "Individuals only (team size 1)"
    return "not specified"


def _fetch_page(opportunity: str, page: int, delay: float) -> list:
    """목록 1페이지 → 아이템 리스트. 실패하면 빈 리스트."""
    try:
        r = requests.get(API, headers=HEADERS, timeout=25,
                         params={"opportunity": opportunity, "page": page,
                                 "per_page": PER_PAGE, "oppstatus": "open"})
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        log.warning("언스탑 API 실패 %s page=%d: %s", opportunity, page, e)
        return []
    finally:
        time.sleep(delay)
    data = payload.get("data") or {}
    return data.get("data") or []


def _to_item(raw: dict) -> dict:
    """API 아이템 1건 → 공통 스키마 dict."""
    oid = raw.get("id")
    url = raw.get("seo_url") or ""
    title = (raw.get("title") or "").strip()
    otype = raw.get("type") or "competitions"
    subtype = raw.get("subtype") or ""
    field = f"{otype} / {subtype}" if subtype else otype

    target = ", ".join(
        (f.get("name") or "").strip() for f in (raw.get("filters") or [])
        if isinstance(f, dict) and f.get("type") == "eligible" and f.get("name"))

    regn = raw.get("regnRequirements") or {}
    start = _iso_date(regn.get("start_regn_dt"))
    # 접수 마감(end_regn_dt)과 대회 종료(end_date)는 다른 경우가 흔하다.
    # 마감일은 반드시 접수 마감을 쓰고, regnRequirements가 없을 때만 폴백.
    deadline = _iso_date(regn.get("end_regn_dt")) or _iso_date(raw.get("end_date"))
    period = f"{start} ~ {deadline}" if start and deadline else (deadline or "")

    region = raw.get("region") or ""
    body = _clean_html(raw.get("details") or "")
    if not body:
        # 본문 필드(details)가 비었으면 페이지 전체 텍스트로 폴백하지 않는다
        # (상세 HTML은 SPA 쉘이라 애초에 본문이 없고, 메뉴만 섞인다).
        log.warning("본문(details) 없음 — 요약으로 대체 id=%s title=%s", oid, title)
        body = f"{title} | {field} | 접수 {period or '기간 미상'}"
    else:
        # 응모대상·팀 인원은 본문 문장에 없고 구조화 필드에만 있다
        head = (f"[Eligibility] {target or 'not specified'}\n"
                f"[Team size] {_team_line(regn)}\n"
                f"[Region] {region or 'not specified'}")
        body = f"{head}\n{body}"

    return {
        "source": "언스탑(해외)",
        "ix": f"unstop-{oid}",
        "url": url,
        "homepage": raw.get("short_url") or url,
        "title": title,
        "field": field,
        "target": target,
        "host": ((raw.get("organisation") or {}).get("name") or "").strip(),
        "period": period,
        "prize": _prize_text(raw.get("prizes")),
        "deadline": deadline,
        "body": body[:BODY_MAX],
        "lang": "en",
        "location": region,
    }


def scrape(pages: int = 2, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """접수중(open) 공모전 + 해커톤 수집 → 공통 스키마 dict 리스트."""
    results: list[dict] = []
    seen: set[str] = set()
    for opportunity in OPPORTUNITIES:
        for page in range(1, pages + 1):
            if len(results) >= max_details:
                break
            rows = _fetch_page(opportunity, page, delay)
            if not rows:
                break
            for raw in rows:
                if len(results) >= max_details:
                    break
                try:
                    item = _to_item(raw)
                except Exception as e:
                    log.warning("항목 파싱 실패 id=%s: %s",
                                (raw or {}).get("id"), e)
                    continue
                if not item["title"] or not item["url"] or item["ix"] in seen:
                    continue
                seen.add(item["ix"])
                results.append(item)
            log.info("언스탑 %s %d페이지: 누적 %d건", opportunity, page, len(results))
    log.info("[언스탑(해외)] 수집 완료: %d건", len(results))
    return results
