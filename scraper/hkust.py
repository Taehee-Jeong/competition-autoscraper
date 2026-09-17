# -*- coding: utf-8 -*-
"""HKUST(홍콩과기대) 대회 수집 — 교내 대회 + HKUST에 게시된 홍콩 외부 대회.

두 사이트 모두 Drupal이라 파서를 공유한다 (위비티가 국내/해외를 한 파일에 둔 것과 같은 구조).

  scrape_calendar()  https://calendar.hkust.edu.hk
      /events/competition               교내 'Competition' 형식 이벤트
      /events/non-hkust?category=1156   외부(홍콩) 주최가 HKUST에 올린 대회
      목록 페이지에는 사이드바 강연이 섞여 들어오므로, 상세의 Event Format이
      Competition인 건만 남긴다.

  scrape_ec()        https://ec.hkust.edu.hk/events  (Entrepreneurship Center)
      해커톤·창업대회 목록. 강연·멘토십 모임이 섞여 있어 제목+본문 키워드로 거른다.

프록시: 이 서버 셸의 HTTPS_PROXY(127.0.0.1:7070)를 hkust 도메인이 타면 간헐적으로
끊긴다(2026-09-13 실측 'Proxy CONNECT aborted'). 직접 접속은 안정적이라 이 모듈은
환경변수 프록시를 무시하는 세션을 쓴다.
"""
import re
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("hkust")

CAL_BASE = "https://calendar.hkust.edu.hk"
CAL_LISTS = [f"{CAL_BASE}/events/competition",
             f"{CAL_BASE}/events/non-hkust?category=1156"]
EC_BASE = "https://ec.hkust.edu.hk"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
BODY_MAX = 8000
HKT = timezone(timedelta(hours=8))

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# '12 Sep 2026' / '1 October 2026' / 'Oct. 1, 2026' / 'October 1st, 2026' / '2026-10-01'
_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
_MDY = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# 본문 안의 마감 문구. 뒤따르는 날짜에 연도가 있을 때만 믿는다.
_DEADLINE_CUE = re.compile(
    r"(?i)(deadline|apply\s+by|applications?\s+(close|due)|registration\s+(closes?|deadline)"
    r"|submit(ted)?\s+by|submissions?\s+(close|due))[^.\n]{0,60}")

COMPETITION_WORDS = re.compile(
    r"(?i)\b(hackathon|competition|challenge|contest|pitch(ing)?|awards?|prizes?|cup)\b")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False          # HTTPS_PROXY 무시 (모듈 docstring 참고)
    s.headers.update(HEADERS)
    return s


def _get(sess: requests.Session, url: str, delay: float = 1.0) -> str:
    r = sess.get(url, timeout=25)
    r.raise_for_status()
    time.sleep(delay)
    return r.text


# ── 날짜 ─────────────────────────────────────────────────────────────────
def _month(name: str):
    return MONTHS.get(name[:3].lower())


def parse_en_date(raw: str | None) -> str | None:
    """영문 날짜 문자열에서 첫 날짜 → 'YYYY-MM-DD'. 연도가 없으면 None."""
    if not raw:
        return None
    m = _ISO.search(raw)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DMY.search(raw)
        if m and _month(m.group(2)):
            d, mo, y = int(m.group(1)), _month(m.group(2)), int(m.group(3))
        else:
            m = _MDY.search(raw)
            if not (m and _month(m.group(1))):
                return None
            mo, d, y = _month(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def iso_to_hk_date(iso: str | None) -> str | None:
    """'2026-07-05T15:59:59Z'(UTC) → 홍콩시간 날짜 '2026-07-05'."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(HKT).strftime("%Y-%m-%d")


def deadline_from_body(body: str) -> str | None:
    """본문의 'deadline …', 'apply by …' 뒤에 연도 있는 날짜가 오면 그 날짜."""
    for m in _DEADLINE_CUE.finditer(body or ""):
        d = parse_en_date(m.group(0))
        if d:
            return d
    return None


# ── 공용 파서 ─────────────────────────────────────────────────────────────
def _body_text(soup: BeautifulSoup) -> str:
    node = soup.select_one(".field--name-body")
    if node is None:
        return ""
    text = node.get_text("\n", strip=True)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return text[:BODY_MAX]


def _field_items(soup: BeautifulSoup, field_class: str) -> list[str]:
    node = soup.select_one(f".{field_class}")
    if node is None:
        return []
    items = [i.get_text(" ", strip=True) for i in node.select(".field__item")]
    return [i for i in items if i]


def _prize_lines(body: str) -> str:
    """상금 언급 줄 최대 3개. 없으면 빈칸."""
    out = []
    for line in body.split("\n"):
        if re.search(r"(?i)(HK\$|US\$|\$|USD|HKD)\s?\d", line) and \
                re.search(r"(?i)prize|award|cash|place|winner", line):
            out.append(line.strip()[:120])
        if len(out) == 3:
            break
    return " / ".join(out)


def is_competition_text(title: str, body: str) -> bool:
    return bool(COMPETITION_WORDS.search(f"{title}\n{body}"))


# ── 캘린더 ────────────────────────────────────────────────────────────────
def calendar_list_links(html: str) -> list[str]:
    """목록 HTML → 이벤트 상세 URL 목록 (순서 유지, 중복 제거).

    실제 목록은 `.view.event-listing` 안에 있다. 그 밖(사이드바 'Featured events')의
    링크는 강연이 대부분이라 애초에 안 모은다. 분류 페이지(/events/competition 등)는
    slug 검사로 거른다.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.select(".view.event-listing a[href]"):
        href = a["href"]
        m = re.match(r"^(?:https?://calendar\.hkust\.edu\.hk)?/events/([A-Za-z0-9][A-Za-z0-9_-]*)$",
                     href)
        if not m:
            continue
        url = f"{CAL_BASE}/events/{m.group(1)}"
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def calendar_nonhkust_links(html: str) -> set[str]:
    """목록 HTML에서 '외부 주최' 블록 안의 링크만 (교내/외부 표시용)."""
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for block in soup.select("[class*='non-hkus']"):
        for a in block.select("a[href]"):
            m = re.match(r"^(?:https?://calendar\.hkust\.edu\.hk)?/events/([A-Za-z0-9][A-Za-z0-9_-]*)$",
                         a["href"])
            if m:
                urls.add(f"{CAL_BASE}/events/{m.group(1)}")
    return urls


def parse_calendar_detail(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    fmt = " ".join(_field_items(soup, "field--name-field-category"))
    host = " ".join(_field_items(soup, "field--name-field-event-organizer")) or \
        " ".join(i.get_text(" ", strip=True)
                 for i in soup.select(".field--name-field-event-organizer .field__item"))
    target = ", ".join(_field_items(soup, "field--name-field-audiences"))
    times = [iso_to_hk_date(t.get("datetime"))
             for t in soup.select(".field--name-field-event-dates time")]
    times = [t for t in times if t]
    start, end = (times[0], times[-1]) if times else (None, None)
    period = f"{start} ~ {end}" if start and end and start != end else (start or "")
    body = _body_text(soup)
    if not body:
        log.warning("캘린더 본문 없음: %s", url)
        body = f"{title} | format: {fmt} | organizer: {host} | period: {period}"
    return {
        "source": "HKUST 캘린더(홍콩)",
        "ix": "hkust-cal-" + url.rstrip("/").rsplit("/", 1)[-1],
        "url": url,
        "homepage": url,
        "title": title,
        "field": f"Competition ({fmt})" if fmt and fmt != "Competition" else "Competition",
        "target": target or "확인필요 (Recommended For 미기재)",
        "host": host,
        "period": period,
        "prize": _prize_lines(body),
        # 본문 마감 문구 우선, 없으면 기간 종료일(대회 당일일 수 있음 → period 참고)
        "deadline": deadline_from_body(body) or end,
        "body": body,
        "lang": "en",
        "event_format": fmt,
    }


def is_calendar_competition(item: dict) -> bool:
    return "competition" in (item.get("event_format") or "").lower()


def scrape_calendar(pages: int = 1, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """HKUST 캘린더 → 공통 스키마 dict 리스트."""
    sess = _session()
    urls, external = [], set()
    for list_url in CAL_LISTS:
        try:
            html = _get(sess, list_url, delay)
        except Exception as e:
            log.warning("캘린더 목록 실패 %s: %s", list_url, e)
            continue
        for u in calendar_list_links(html):
            if u not in urls:
                urls.append(u)
        external |= calendar_nonhkust_links(html)
        if "non-hkust" in list_url:
            external |= set(calendar_list_links(html))
    log.info("HKUST 캘린더 목록: %d건 (외부 주최 %d건)", len(urls), len(external))

    items = []
    for url in urls[:max_details]:
        try:
            it = parse_calendar_detail(_get(sess, url, delay), url)
        except Exception as e:
            log.warning("캘린더 상세 실패 %s: %s", url, e)
            continue
        if not is_calendar_competition(it):
            log.info("Competition 아님(%s) 건너뜀: %s", it.get("event_format"), it["title"])
            continue
        it["location"] = "홍콩(외부 주최)" if url in external else "HKUST 교내"
        items.append(it)
    log.info("HKUST 캘린더: %d건", len(items))
    return items


# ── 창업센터 ──────────────────────────────────────────────────────────────
def ec_list_cards(html: str) -> list[dict]:
    """목록 HTML → [{title, url, deadline}]. 카드는 <a> 하나가 h3와 마감을 감싼다."""
    soup = BeautifulSoup(html, "html.parser")
    cards, seen = [], set()
    for h3 in soup.select(".title h3"):
        a = h3.find_parent("a")
        if a is None or not a.get("href"):
            continue
        url = a["href"]
        if url.startswith("/"):
            url = EC_BASE + url
        if url in seen:
            continue
        seen.add(url)
        t = a.find("time")
        cards.append({"title": h3.get_text(" ", strip=True), "url": url,
                      "deadline": iso_to_hk_date(t.get("datetime")) if t else None})
    return cards


def _ec_label_value(soup: BeautifulSoup, label: str) -> str:
    """'Deadline :' 같은 span.subhead 라벨의 값 부분."""
    for sp in soup.select("span.subhead"):
        if label.lower() in sp.get_text(" ", strip=True).lower():
            full = sp.parent.get_text(" ", strip=True)
            return re.sub(r"^.*?:\s*", "", full, count=1).strip()
    return ""


def parse_ec_detail(html: str, url: str, card: dict | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else (card or {}).get("title", "")
    host = _ec_label_value(soup, "Organised by") or "HKUST Entrepreneurship Center"
    body = _body_text(soup)
    if not body:
        log.warning("창업센터 본문 없음: %s", url)
        body = f"{title} | organiser: {host}"
    m = re.search(r"(?i)\bopen to\b[^.\n]*", body)
    target = m.group(0).strip() if m else "확인필요 (본문에 대상 미기재)"
    deadline = (deadline_from_body(body)
                or parse_en_date(_ec_label_value(soup, "Deadline"))
                or (card or {}).get("deadline"))
    return {
        "source": "HKUST 창업센터(홍콩)",
        "ix": "hkust-ec-" + url.rstrip("/").rsplit("/", 1)[-1],
        "url": url,
        "homepage": url,
        "title": title,
        "field": "창업·해커톤",
        "target": target,
        "host": host,
        "period": _ec_label_value(soup, "Deadline"),
        "prize": _prize_lines(body),
        "deadline": deadline,
        "body": body,
        "lang": "en",
        "location": "HKUST 창업센터",
    }


def scrape_ec(pages: int = 2, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """HKUST 창업센터 이벤트 중 대회성 건만 → 공통 스키마 dict 리스트."""
    sess = _session()
    cards = []
    for page in range(pages):
        try:
            html = _get(sess, f"{EC_BASE}/events?page={page}", delay)
        except Exception as e:
            log.warning("창업센터 목록 실패 page=%d: %s", page, e)
            break
        got = ec_list_cards(html)
        if not got:
            break
        cards.extend(c for c in got if c["url"] not in {x["url"] for x in cards})
    log.info("HKUST 창업센터 목록: %d건", len(cards))

    items = []
    for card in cards[:max_details]:
        try:
            it = parse_ec_detail(_get(sess, card["url"], delay), card["url"], card)
        except Exception as e:
            log.warning("창업센터 상세 실패 %s: %s", card["url"], e)
            continue
        if not is_competition_text(it["title"], it["body"]):
            log.info("대회 아님 건너뜀: %s", it["title"])
            continue
        items.append(it)
    log.info("HKUST 창업센터: %d건", len(items))
    return items
