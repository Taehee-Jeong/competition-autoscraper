# -*- coding: utf-8 -*-
"""
드리븐데이터(drivendata.org) 해외 데이터사이언스 대회 스크래퍼.

URL 구조 (2026-07 실제 확인):
  - 목록:  https://www.drivendata.org/competitions/
           서버 렌더링 단일 페이지. 페이지네이션이 없어 접수중/종료 70건이 한 장에 다 있다.
           접수중만 고르려면 div.panel-container.active-comp 로 선별한다.
  - 상세:  https://www.drivendata.org/competitions/{id}/{slug}/

robots.txt 주의: /competitions/search/ (카테고리·타입 필터 링크)는 Disallow다.
따라서 필터 URL은 절대 요청하지 않고 /competitions/ 인덱스 한 장만 읽는다.
인덱스와 상세 페이지는 Disallow 대상이 아니다.

목록 카드 중 두 종류는 상세를 요청하지 않는다:
  - /benchmarks/{id}/... : 마감·상금이 없는 벤치마크라 공모전 후보가 아님 → 건너뜀
  - 외부 절대 URL       : 타 플랫폼 호스팅이라 본문 마크업이 다름 → 목록 정보만으로 수록
"""
import re
import time
import logging
import requests
from datetime import date
from bs4 import BeautifulSoup
from urllib.parse import urljoin

log = logging.getLogger("drivendata")

BASE = "https://www.drivendata.org"
LIST_URL = f"{BASE}/competitions/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

SOURCE_NAME = "드리븐데이터(해외)"

# 접수중 카드. 종료 대회(61건)와 같은 페이지에 섞여 있어 active-comp가 필수다.
CARD_SELECTOR = "div.panel-container.active-comp"
# 공고 본문 영역. main 태그는 네비/사이드바/푸터까지 5만자를 포함하므로 절대 쓰지 않는다.
BODY_ID = "content-page"

# Django 날짜 포맷이라 월 약어가 Jan./Feb./March/April/Sept. 처럼 섞여 나온다.
MONTHS = {"jan": 1, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
          "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "aug": 8,
          "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _get(url: str, delay: float = 1.0) -> BeautifulSoup:
    """예의 있는 요청: 요청 간 delay를 두고, 실패 시 1회 재시도."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            time.sleep(delay)
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning("요청 실패(%s/2): %s (%s)", attempt + 1, url, e)
            time.sleep(3)
    raise RuntimeError(f"페이지 요청 실패: {url}")


def _parse_deadline(raw: str) -> str | None:
    """마감 표기 → 'YYYY-MM-DD'. 파싱 못 하면 None.

    두 가지 형태가 실제로 나온다:
      - span.end-date['title']  'Sept. 16, 2026, 11:59 p.m. UTC'
      - 외부 호스팅 카드 텍스트  'Closes 27 Aug 2026'  (title 속성이 없음)
    """
    if not raw:
        return None
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})", raw)
    if m:
        mon, day, year = MONTHS.get(m.group(1).lower()), m.group(2), m.group(3)
    else:
        m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})", raw)
        if not m:
            return None
        mon, day, year = MONTHS.get(m.group(2).lower()), m.group(1), m.group(3)
    if not mon:
        return None
    try:
        return date(int(year), mon, int(day)).isoformat()
    except ValueError:
        return None


def _text(node, selector: str) -> str:
    """셀렉터가 없으면 빈 문자열 (마크업 변경에도 죽지 않게)."""
    found = node.select_one(selector) if node else None
    return found.get_text(" ", strip=True) if found else ""


def _host(node) -> str:
    """주최는 로고 이미지의 alt('Hosted by DrivenData')에만 들어있다."""
    img = node.find("img", alt=lambda v: v and v.startswith("Hosted by")) if node else None
    return re.sub(r"^Hosted by\s*", "", img.get("alt", "")).strip() if img else ""


def _period(node) -> str:
    """접수기간 전용 표기가 없어 마감 표기를 원문 그대로 쓴다."""
    span = node.select_one("span.end-date") if node else None
    if not span:
        return ""
    return (span.get("title") or span.get_text(" ", strip=True) or "").strip()


def _summary_body(card: dict) -> str:
    """본문을 못 가져왔을 때의 대체 본문 (제목+분야+기간). 전체 텍스트 폴백은 금지."""
    return (f"{card.get('title','')} | field: {card.get('field','')} | "
            f"host: {card.get('host','')} | deadline: {card.get('period','')}")


def _extract_target(body: str) -> str:
    """응모대상 전용 필드가 없어 본문의 자격 문장을 쓴다. 없으면 고정값."""
    for line in body.split("\n"):
        if re.search(r"eligib", line, re.I):
            # 본문 줄이 링크에서 잘려 '. Participants may…'처럼 시작할 수 있다.
            return line.strip(" .,;·")[:300]
    return "상세 공고 확인"


def list_active_cards() -> list[dict]:
    """목록 페이지의 '접수중' 카드에서 기본 정보 수집.

    상세를 못 읽는 카드(외부 호스팅)도 여기 정보만으로 수록할 수 있게
    카드 단계에서 title/href/기간/상금/분야/주최를 모두 담아둔다.
    """
    soup = _get(LIST_URL)
    cards: list[dict] = []
    for card in soup.select(CARD_SELECTOR):
        try:
            a = card.select_one("h3.panel-competition-title a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            if "/benchmarks/" in href:
                log.info("벤치마크는 공모전이 아니라 건너뜀: %s", href)
                continue
            url = urljoin(BASE, href)
            m = re.search(r"/competitions/(\d+)/", href)
            internal = url.startswith(BASE)
            ix = (f"drivendata-{m.group(1)}" if internal and m
                  else "drivendata-ext-" + href.rstrip("/").rsplit("/", 1)[-1])
            category = _text(card, "a.text-category")
            cards.append({
                "ix": ix,
                "url": url,
                "internal": internal,
                "title": a.get_text(" ", strip=True),
                "field": f"데이터사이언스 / {category}" if category else "데이터사이언스",
                "host": _host(card),
                "period": _period(card),
                "prize": _text(card, "span.prize"),
            })
        except Exception as e:
            log.warning("목록 카드 파싱 실패: %s", e)
    log.info("드리븐데이터 접수중 %d건", len(cards))
    return cards


def fetch_competition_detail(card: dict) -> dict:
    """상세 페이지 1건 파싱 → 카드 정보를 상세 값으로 보강."""
    soup = _get(card["url"])
    item = dict(card)

    h1 = soup.find("h1")
    if h1:
        item["title"] = h1.get_text(" ", strip=True)

    # 본문: div#content-page 만. 못 찾으면 전체 텍스트 폴백 대신 요약으로 채운다
    # (main 태그에는 네비·사이드바·푸터 5만자가 섞여 판정을 오염시킨다).
    node = soup.find("div", id=BODY_ID)
    if node is None:
        log.warning("본문 영역(#%s) 없음 — 요약으로 대체 %s", BODY_ID, card["url"])
        item["body"] = _summary_body(card)
    else:
        item["body"] = node.get_text("\n", strip=True)[:8000]

    # 상세에도 같은 셀렉터가 있어 목록 값을 덮어쓴다 (목록이 비었을 때만 보존).
    item["period"] = _period(soup) or card.get("period", "")
    item["prize"] = _text(soup, "span.prize") or card.get("prize", "")
    item["host"] = _host(soup) or card.get("host", "")
    return item


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """접수중 대회를 수집 → 공통 스키마 dict 리스트.

    목록이 페이지네이션 없는 단일 페이지라 `pages`는 쓰지 않는다
    (다른 소스와 등록 시그니처를 맞추기 위해 남겨둠).
    """
    del pages
    try:
        cards = list_active_cards()
    except Exception as e:
        log.warning("드리븐데이터 목록 수집 실패: %s", e)
        return []

    results: list[dict] = []
    for card in cards[:max_details]:
        try:
            if card["internal"]:
                item = fetch_competition_detail(card)
            else:
                # 외부 플랫폼 호스팅 — 상세 마크업이 달라 요청하지 않는다.
                log.info("외부 호스팅이라 목록 정보만 수록: %s", card["url"])
                item = dict(card)
                item["body"] = _summary_body(card)
            item.pop("internal", None)
            item["source"] = SOURCE_NAME
            item["homepage"] = item["url"]
            item["deadline"] = _parse_deadline(item.get("period", ""))
            item["target"] = _extract_target(item["body"])
            item["lang"] = "en"
            item["location"] = "온라인 (전 세계)"
            results.append(item)
        except Exception as e:
            log.warning("상세 파싱 실패 ix=%s: %s", card.get("ix"), e)
    log.info("[%s] 상세 수집 완료: %d건", SOURCE_NAME, len(results))
    return results
