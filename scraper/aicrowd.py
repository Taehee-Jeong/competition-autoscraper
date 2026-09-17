# -*- coding: utf-8 -*-
"""
에이아이크라우드(aicrowd.com) AI/ML 챌린지 스크래퍼 (해외·영문).

URL 구조 (2026-07 실측):
  - 목록: https://www.aicrowd.com/challenges?status={running|starting_soon}&page={n}
  - 상세: https://www.aicrowd.com/challenges/{slug}

주의 1) 마감일·상금·주최·기간은 상세 페이지에 서버렌더되지 않는다(React 전용).
        반드시 목록 카드에서 뽑아 상세 fetch로 넘긴다. wevity.py처럼 ID만 모아
        상세만 파싱하면 해당 필드가 전부 빈다.
주의 2) robots.txt가 Crawl-delay: 10 을 요구한다(/challenges 는 허용, /participants 만
        금지). 다른 소스의 delay=1.0을 그대로 쓰면 정책 위반이므로 기본 10초.
주의 3) X-Requested-With: XMLHttpRequest 를 붙이면 JS 응답이 와서 카드가 0개가 된다.
        브라우저 UA만 보낼 것.
주의 4) 마감일이 2030·2045·2100년인 '사실상 영구개방(Post-challenge)' 더미가 다수라
        마감일만 믿으면 죽은 대회가 대량 유입된다 → _is_stale()로 걸러낸다.
"""
import re
import time
import logging
import requests
from datetime import date, timedelta
from bs4 import BeautifulSoup

log = logging.getLogger("aicrowd")

BASE = "https://www.aicrowd.com"
LIST_URL = f"{BASE}/challenges"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# robots.txt Crawl-delay: 10 (실측). 낮추지 말 것.
DELAY = 10.0

# 접수중 + 곧 시작 (completed/draft는 수집 대상 아님)
STATUSES = ("running", "starting_soon")

CARD_SELECTOR = "div.card.card-challenge"
# 목록에는 /challenges/<slug>/leaderboards, /discussion, /problems/... 하위 링크가
# 섞여 있으므로 루트 형태만 대회로 인정한다.
SLUG_PATTERN = re.compile(r"^/challenges/([a-z0-9\-]+)$")

# 상세 본문 영역 (실측 12,661자, 네비/푸터 오염 0). 못 찾으면 전체 텍스트로
# 폴백하지 않는다 — 페이지 전체를 넣으면 판정용 본문이 오염된다.
BODY_SELECTOR = "div.md-content.ck-content"

# 종료/영구개방 더미 판별
STALE_BADGE_PATTERN = re.compile(r"post[\s\-]*challenge|completed|ended", re.I)
MAX_FUTURE_DAYS = 365


def _get(url: str, params: dict | None = None, delay: float = DELAY) -> BeautifulSoup:
    """예의 있는 요청: 요청 후 delay를 두고, 실패 시 1회 재시도."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            r.raise_for_status()
            time.sleep(delay)
            return BeautifulSoup(r.text, "html.parser")
        except requests.TooManyRedirects as e:
            # 일부 하위 트랙 대회는 자기 자신으로 302를 무한 반복한다(서버측).
            # 재시도해도 동일하므로 즉시 포기한다.
            log.warning("무한 리다이렉트 — 건너뜀: %s (%s)", url, e)
            break
        except Exception as e:
            log.warning("요청 실패(%s/2): %s %s (%s)", attempt + 1, url, params or "", e)
            time.sleep(delay)
    raise RuntimeError(f"페이지 요청 실패: {url} {params or ''}")


def _parse_deadline(attr: str) -> str | None:
    """뱃지 title 속성 '2026-07-31 23:59:00 UTC' → '2026-07-31'. 실패 시 None."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", (attr or "").strip())
    if not m:
        return None
    try:
        date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return m.group(1)


def _parse_card(card) -> dict | None:
    """목록 카드 1개 → 부분 dict (상세에 없는 마감일/상금/주최를 여기서 확보)."""
    slug, href = None, ""
    for a in card.select("h5.card-title a[href]") or []:
        m = SLUG_PATTERN.match(a["href"].strip())
        if m:
            slug, href = m.group(1), a["href"].strip()
            break
    if not slug:
        return None
    link = card.select_one("h5.card-title a[href]")
    title = link.get_text(strip=True) if link else slug

    badge = card.select_one("span.badge.badge-primary")
    badge_text = badge.get_text(" ", strip=True) if badge else ""
    deadline = _parse_deadline(badge.get("title", "")) if badge else None
    period = badge.get("title", "").strip() if badge else ""
    if badge_text and period:
        period = f"{badge_text} ({period})"
    elif badge_text:
        period = badge_text

    prize_node = card.select_one(".prizes-breakdown")
    prize = prize_node.get_text(" ", strip=True) if prize_node else ""

    tags = [x.get_text(strip=True) for x in card.select(".category-group .badge-outline")]
    field = " ".join(t for t in tags if t) or "AI/ML 챌린지"

    hosts = [x.get("title", "").strip() for x in card.select(".card-footer a span[title]")]
    host = " / ".join(h for h in hosts if h) or "AIcrowd"

    summary_node = card.select_one("p.card-text")
    summary = summary_node.get_text(" ", strip=True) if summary_node else ""

    url = BASE + href
    return {
        "source": "AIcrowd(해외)",
        "ix": f"aicrowd-{slug}",
        "url": url,
        "homepage": url,
        "title": title,
        "field": field,
        # 사이트에 응모대상 필드가 없고 본문에도 eligibility 문구가 없다(실측).
        # 여기서 응모대상을 추출하려 하면 안 된다.
        "target": "참가자격 제한 없음(공개 참가) — 상세 Rules 확인",
        "host": host,
        "period": period,
        "prize": prize,
        "deadline": deadline,
        "location": "",
        "lang": "en",
        "body": "",
        "_badge": badge_text,
        "_summary": summary,
    }


def _is_stale(item: dict, today: date) -> bool:
    """종료(Post-challenge)·영구개방 더미면 True."""
    if STALE_BADGE_PATTERN.search(item.get("_badge", "")):
        return True
    dl = item.get("deadline")
    if dl:
        try:
            if date.fromisoformat(dl) > today + timedelta(days=MAX_FUTURE_DAYS):
                return True
        except ValueError:
            return False
    return False


def list_challenges(pages: int = 2, today: date | None = None) -> list[dict]:
    """접수중/개시예정 목록에서 카드 파싱 → 부분 dict 리스트."""
    today = today or date.today()
    items: list[dict] = []
    seen: set[str] = set()
    for status in STATUSES:
        for page in range(1, pages + 1):
            try:
                soup = _get(LIST_URL, params={"status": status, "page": page})
            except Exception as e:
                log.warning("목록 요청 실패 status=%s page=%d: %s", status, page, e)
                break
            cards = soup.select(CARD_SELECTOR)
            if not cards:
                break
            for card in cards:
                try:
                    item = _parse_card(card)
                except Exception as e:
                    log.warning("카드 파싱 실패 status=%s page=%d: %s", status, page, e)
                    continue
                if not item or item["ix"] in seen:
                    continue
                if _is_stale(item, today):
                    log.info("영구개방/종료 대회 제외: %s (%s)",
                             item["title"], item["deadline"])
                    continue
                seen.add(item["ix"])
                items.append(item)
            log.info("AIcrowd %s %d페이지: 누적 %d건", status, page, len(items))
    return items


def fetch_detail(item: dict) -> dict:
    """상세 페이지에서 본문(body)만 채워 완성 dict 반환.

    마감일/상금/주최/기간은 이미 목록 카드에서 채워져 있으므로 건드리지 않는다.
    """
    soup = _get(item["url"])

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        t = re.sub(r"^\s*AIcrowd\s*\|\s*", "", og["content"])
        t = re.sub(r"\s*\|\s*Challenges\s*$", "", t).strip()
        if t:
            item["title"] = t

    node = soup.select_one(BODY_SELECTOR)
    if node is None:
        log.warning("본문 영역(%s) 없음 — 요약으로 대체 ix=%s", BODY_SELECTOR, item["ix"])
        body = " | ".join(x for x in [item["title"], item["field"],
                                      item["period"], item["_summary"]] if x)
    else:
        body = node.get_text("\n", strip=True)
    item["body"] = body[:8000]

    item.pop("_badge", None)
    item.pop("_summary", None)
    return item


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """AIcrowd 접수중/개시예정 챌린지 수집 → 공통 스키마 dict 리스트."""
    cards = list_challenges(pages=pages)
    results: list[dict] = []
    for item in cards[:max_details]:
        try:
            results.append(fetch_detail(item))
        except Exception as e:
            log.warning("상세 파싱 실패 ix=%s: %s", item.get("ix"), e)
    log.info("[AIcrowd(해외)] 상세 수집 완료: %d건", len(results))
    return results
