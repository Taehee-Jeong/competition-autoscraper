# -*- coding: utf-8 -*-
"""MLH(Major League Hacking) 시즌 해커톤 수집 — Inertia.js SSR JSON 파싱.

  https://www.mlh.com/events → 301 → https://www.mlh.com/seasons/{현재시즌}/events

옛 도메인 mlh.io 는 www.mlh.com 으로 이전됐다(301). `/events` 는 항상 '현재
시즌'으로 리다이렉트되므로 연도를 하드코딩하지 않는다. 페이지네이션이 없어
요청 1건으로 시즌 전체(2026-07 실측: upcoming 61건)를 받는다.

HTML은 Tailwind 유틸리티 클래스뿐이라 DOM 파싱이 취약하지만, Inertia.js가
`<script data-page="app">` 안에 이벤트 배열 전체를 JSON으로 심어두므로 그것만
읽는다. `props.upcomingEvents` 가 목록이다. (__NEXT_DATA__ / ld+json 은 없다.
`X-Inertia: true` 로 순수 JSON을 요청하면 버전 불일치 409라 쓰지 않는다.
robots.txt가 /graphql 을 명시적으로 금지하므로 GraphQL도 쓰지 않는다.)

**상세 페이지는 아예 받지 않는다.** 상세 `/events/{slug}/prizes` 를 실제로
받아보면 본문이 전 이벤트 공통 보일러플레이트 186자뿐이고(challenges=[]),
event 딕셔너리는 목록과 100% 동일하다. 즉 상세 요청은 순수 낭비이자 메뉴
텍스트 오염원이라, devpost.py 선례대로 목록 필드만으로 body를 합성한다.
실제 참가자격·팀 규정 원문은 각 해커톤 자체 사이트(websiteUrl)에만 있고
마크업이 제각각이라 통일 수집이 불가능하다.

주의: deadline 은 '접수 마감일'이 아니라 '행사 종료일'(endsAt)이다. MLH는
지원 마감일을 공개하지 않는다(각 대회 사이트 소관). 지난 공고 제거 용도로는
정확하지만, 마감 임박 알림 기준으로는 이미 접수가 닫혔을 수 있다.
"""
import re
import time
import json
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

log = logging.getLogger("mlh")

BASE = "https://www.mlh.com"
LIST_URL = f"{BASE}/events"          # 현재 시즌으로 자동 리다이렉트
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

SOURCE = "MLH 시즌 해커톤(해외)"
# 이벤트 배열이 통째로 들어있는 유일한 노드. 이게 없으면 수집할 게 없다.
PAGE_SCRIPT_ATTRS = {"data-page": "app"}
FIELD = "해커톤"
HOST = "Major League Hacking"
# 개별 자격요건 필드가 없다. MLH 시즌 이벤트는 리그 차원에서 학생 해커톤이다.
TARGET = "대학생 등 학생 해커 (MLH 공식 시즌 해커톤, 개별 참가자격은 각 대회 사이트 확인)"

BODY_MAX = 8000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _iso_date(s: str | None) -> str | None:
    """'2027-02-07T23:59:59Z' → '2027-02-07'. 형식이 다르면 None."""
    if not s or not isinstance(s, str):
        return None
    head = s[:10]
    return head if DATE_RE.match(head) else None


def _fetch_events(delay: float) -> list:
    """현재 시즌 목록 1건 요청 → upcomingEvents 리스트. 실패하면 빈 리스트."""
    try:
        r = requests.get(LIST_URL, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        log.warning("MLH 목록 요청 실패 %s: %s", LIST_URL, e)
        return []
    finally:
        time.sleep(delay)

    soup = BeautifulSoup(r.text, "html.parser")
    tag = soup.find("script", attrs=PAGE_SCRIPT_ATTRS)
    if tag is None:
        # 페이지 전체 텍스트로 폴백하지 않는다 — Tailwind 셸이라 메뉴만 나온다.
        log.warning("Inertia 페이로드(script[data-page=app]) 없음: %s", r.url)
        return []
    try:
        payload = json.loads(tag.string or tag.get("data-page") or "{}")
    except Exception as e:
        log.warning("Inertia 페이로드 JSON 파싱 실패: %s", e)
        return []

    props = payload.get("props") or {}
    events = props.get("upcomingEvents") or []
    log.info("MLH %s시즌: upcoming %d건", props.get("seriesName") or "?", len(events))
    return events


def _restrictions(e: dict) -> str:
    """customFields.underserved_types = 참가자격 제한 신호 (예: 'Women Only')."""
    types = (e.get("customFields") or {}).get("underserved_types") or []
    return ", ".join(str(t).strip() for t in types if t)


def _to_item(e: dict) -> dict:
    """이벤트 1건 → 공통 스키마 dict."""
    slug = e.get("slug") or ""
    title = (e.get("name") or "").strip()   # 뒤 공백이 붙은 값이 실제로 있다
    start = _iso_date(e.get("startsAt"))
    end = _iso_date(e.get("endsAt"))
    date_range = (e.get("dateRange") or "").strip()   # 'FEB 06 - 07' (연도 없음)
    period = (f"{date_range} ({start} ~ {end})"
              if date_range and start and end else (date_range or ""))

    location = (e.get("location") or "").strip()
    fmt = e.get("formatType") or ""          # physical / digital
    region = e.get("region") or ""           # AMER / APAC / EMEA
    country = (e.get("venueAddress") or {}).get("country") or ""
    site = e.get("websiteUrl") or ""
    restricted = _restrictions(e)

    # 공고 본문이 존재하지 않는 사이트라 목록 필드로 합성한다.
    # 페이지 텍스트를 긁지 않으므로 네비게이션·푸터가 섞일 여지가 없다.
    if location or date_range:
        parts = [title, location or "location n/a", fmt or "format n/a",
                 f"region: {region or 'n/a'}", f"country: {country or 'n/a'}",
                 period or "dates n/a", f"website: {site or 'n/a'}"]
        body = " | ".join(parts)
        if restricted:
            body += f"\n[Eligibility restriction] {restricted}"
    else:
        log.warning("목록 필드 부족 — 요약으로 대체 slug=%s", slug)
        body = f"{title} | {FIELD} | {period or '기간 미상'}"

    url = urljoin(BASE, e.get("url") or f"/events/{slug}/prizes")
    return {
        "source": SOURCE,
        "ix": f"mlh-{slug or e.get('id', '')}",
        "url": url,
        "homepage": site or url,
        "title": title,
        "field": FIELD,
        "target": f"{TARGET} / 제한: {restricted}" if restricted else TARGET,
        "host": HOST,
        "period": period,
        "prize": "",            # MLH는 목록·상세 모두 상금 필드 자체가 없다
        "deadline": end,        # 접수 마감이 아니라 행사 종료일 (모듈 독스트링 참고)
        "body": body[:BODY_MAX],
        "lang": "en",
        "location": location,
    }


def scrape(pages: int = 2, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """현재 시즌 upcoming 해커톤 수집 → 공통 스키마 dict 리스트.

    pages 는 레지스트리 호출 규약을 맞추기 위한 인자이고 실제로는 쓰지 않는다
    (MLH 목록은 페이지네이션이 없어 요청 1건이 시즌 전체다).
    max_details 는 반환 건수 상한이다.
    """
    results: list[dict] = []
    seen: set[str] = set()
    for e in _fetch_events(delay):
        if len(results) >= max_details:
            break
        try:
            item = _to_item(e)
        except Exception as ex:
            log.warning("항목 파싱 실패 slug=%s: %s", (e or {}).get("slug"), ex)
            continue
        if not item["title"] or not item["url"] or item["ix"] in seen:
            continue
        seen.add(item["ix"])
        results.append(item)
    log.info("[%s] 수집 완료: %d건", SOURCE, len(results))
    return results
