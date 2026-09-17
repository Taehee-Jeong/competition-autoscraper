# -*- coding: utf-8 -*-
"""HKU 경영대(HKUBS) 학부 'Upcoming Competitions' 수집.

  https://ug.hkubs.hku.hk/competition?timing=upcoming
      서버 렌더링, 로그인 불필요. 카드 `a.card-blk__item`, 12개/페이지,
      페이지는 경로식(`/competition/page2?timing=upcoming`).
      카드 정보줄에 "Deadline: 20 Sep 2026 HKT23:59" / "Location: Hong Kong" 이 있고
      마감 지난 건은 같은 줄에 "(Closed)" 가 붙는다.

게시물 상당수는 BOCHK·EY·Deloitte·HSBC·Natixis 같은 홍콩 전체 대학 대상 스폰서 대회이고,
일부만 HKU 내부용이다. 어느 쪽인지 기계가 확정할 수 없으므로 버리지 않고
본문의 자격 문장을 target에 옮겨 담아 검토자가 판단하게 한다.
본문이 HKU 한정으로 읽히면 target 앞에 "[HKU 한정?] " 를 붙인다.

프록시: hkust 모듈과 같은 이유로(셸의 HTTPS_PROXY가 홍콩 사이트에서 끊김)
환경변수 프록시를 무시하는 세션을 쓴다.
"""
import re
import time
import logging

import requests
from bs4 import BeautifulSoup

from scraper.hkust import parse_en_date, deadline_from_body, HEADERS, BODY_MAX

log = logging.getLogger("hkubs")

BASE = "https://ug.hkubs.hku.hk"
SOURCE = "HKU경영대 대회목록(홍콩)"

# 자격 문장 후보 줄 (target 에 옮길 것)
_ELIG_LINE = re.compile(r"(?i)eligib|open to|\bstudents\b")
# HKU 한정으로 읽히는 표현
_HKU_ONLY = re.compile(
    r"(?i)\bHKU\s+(students?|undergraduates?|UG\b)|\bHKUBS\s+students?\b"
    r"|\b(only|exclusively)\s+(open\s+)?(to|for)\s+HKU\b|\bHKU\s+students?\s+only\b")
_MESSAGE_FROM = re.compile(r"\[\s*Message from ([^\]]{2,120})\]")
_MONEY = re.compile(r"(?i)(HK\$|US\$|RMB|USD|HKD|\$)\s?\d[\d,]*")
# homepage 후보에서 제외할 링크 (첨부 PDF·구글폼·SNS·HKU 자체)
_NOT_HOMEPAGE = re.compile(
    r"(?i)hku\.hk|\.pdf($|\?)|forms\.gle|docs\.google\.com/forms|instagram\.com"
    r"|facebook\.com|linkedin\.com|mailto:")


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


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


_BLOCK = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "div"]


def block_text(node) -> str:
    """본문 노드 → 블록 요소(p/li/…)와 <br> 단위로만 줄을 나눈 텍스트.

    get_text("\n") 은 <strong>·<a> 같은 인라인 태그에서도 줄을 끊어 자격 문장이
    조각나므로, 잎 블록마다 공백으로 이어 붙인 뒤 <br> 위치에서만 줄을 나눈다.
    """
    for br in node.find_all("br"):
        br.replace_with("\n")
    leaves = [el for el in node.find_all(_BLOCK) if not el.find(_BLOCK)] or [node]
    lines = []
    for el in leaves:
        lines += [_clean(x) for x in el.get_text(" ").split("\n") if _clean(x)]
    return "\n".join(lines)[:BODY_MAX]


def _split_info(texts: list[str]) -> dict:
    """['Deadline: 20 Sep 2026 HKT23:59 (Closed)', 'Location: Hong Kong'] → dict."""
    out = {"deadline_text": "", "location": "", "closed": False}
    for t in texts:
        t = _clean(t)
        if "(Closed)" in t:
            out["closed"] = True
            t = t.replace("(Closed)", "").strip()
        if t.lower().startswith("deadline:"):
            out["deadline_text"] = t.split(":", 1)[1].strip()
        elif t.lower().startswith("location:"):
            out["location"] = t.split(":", 1)[1].strip()
    return out


# ── 목록 ─────────────────────────────────────────────────────────────────
def list_cards(html: str) -> list[dict]:
    """목록 HTML → [{title, url, deadline_text, deadline, location, closed}] (순서 유지)."""
    soup = BeautifulSoup(html, "html.parser")
    cards, seen = [], set()
    for a in soup.select("a.card-blk__item[href]"):
        href = a["href"]
        if not re.match(r"^(?:https?://ug\.hkubs\.hku\.hk)?/competition/[^/?#]+$", href):
            continue
        url = href if href.startswith("http") else BASE + href
        if url in seen:
            continue
        seen.add(url)
        t = a.select_one(".card-blk__content .card-blk__title") or a.select_one(".card-blk__content")
        info = _split_info([s.get_text(" ", strip=True)
                            for s in a.select("ul.card-blk__info-c li.card-blk__info "
                                              "span.card-blk__info-text")])
        cards.append({"title": _clean(t.get_text(" ", strip=True)) if t else "",
                      "url": url,
                      "deadline": parse_en_date(info["deadline_text"]),
                      **info})
    return cards


# ── 상세 ─────────────────────────────────────────────────────────────────
def _target_from_body(body: str) -> str:
    """자격으로 읽히는 줄 최대 4개. 'Eligibility:' 제목줄은 바로 다음 줄까지 같이 담는다."""
    lines = body.split("\n")
    picked = []
    for i, l in enumerate(lines):
        if re.search(r"(?i)eligib", l):
            picked += lines[i:i + 2]
    picked += [l for l in lines if _ELIG_LINE.search(l)]
    out = []
    for l in picked:
        if l and l not in out:
            out.append(l[:200])
    return " / ".join(out[:4])


def _prize_lines(body: str) -> str:
    out = [l.strip()[:120] for l in body.split("\n") if _MONEY.search(l)]
    return " / ".join(out[:3])


def _homepage(node) -> str:
    for a in node.select("a[href]"):
        href = a["href"]
        if href.startswith("http") and not _NOT_HOMEPAGE.search(href):
            return href
    return ""


def parse_detail(html: str, url: str, card: dict | None = None) -> dict:
    card = card or {}
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1.page-title") or soup.find("h1")
    title = _clean(h1.get_text(" ", strip=True)) if h1 else card.get("title", "")
    info = _split_info([s.get_text(" ", strip=True)
                        for s in soup.select("div.info-blk .info-blk__text")])
    deadline_text = info["deadline_text"] or card.get("deadline_text", "")
    location = info["location"] or card.get("location", "")

    node = soup.select_one("div.ckec")
    if node is not None:
        homepage = _homepage(node)
        body = block_text(node)
    else:
        log.warning("HKUBS 본문 없음: %s", url)
        body = f"{title} | deadline: {deadline_text} | location: {location}"
        homepage = ""

    target = _target_from_body(body) or "확인필요 (본문에 자격 미기재)"
    if _HKU_ONLY.search(body):
        target = "[HKU 한정?] " + target
    m = _MESSAGE_FROM.search(body)
    return {
        "source": SOURCE,
        "ix": "hkubs-" + url.rstrip("/").rsplit("/", 1)[-1],
        "url": url,
        "homepage": homepage or url,
        "title": title,
        "field": "경영·금융 (HKU Business School 게시)",
        "target": target,
        "host": _clean(m.group(1)) if m else "",
        "period": f"Deadline: {deadline_text}" if deadline_text else "",
        "prize": _prize_lines(body),
        # 게시판 마감 표기 우선(홍콩 현지 날짜), 없으면 본문 마감 문구
        "deadline": parse_en_date(deadline_text) or card.get("deadline")
        or deadline_from_body(_clean(body)),
        "body": body,
        "lang": "en",
        "location": "홍콩 (HKU 게시)" if not location or location.lower() == "hong kong"
        else f"{location} (HKU 게시)",
    }


# ── 진입점 ────────────────────────────────────────────────────────────────
def scrape(pages: int = 2, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """HKUBS Upcoming Competitions → 공통 스키마 dict 리스트. '(Closed)' 카드는 건너뜀."""
    sess = _session()
    cards = []
    for page in range(1, pages + 1):
        list_url = (f"{BASE}/competition?timing=upcoming" if page == 1
                    else f"{BASE}/competition/page{page}?timing=upcoming")
        try:
            got = list_cards(_get(sess, list_url, delay))
        except Exception as e:
            log.warning("HKUBS 목록 실패 page=%d: %s", page, e)
            break
        if not got:
            break
        known = {c["url"] for c in cards}
        cards.extend(c for c in got if c["url"] not in known)
        if len(got) < 12:
            break
    open_cards = [c for c in cards if not c["closed"]]
    log.info("HKUBS 목록: %d건 (마감 %d건 제외)", len(cards), len(cards) - len(open_cards))

    items = []
    for card in open_cards[:max_details]:
        try:
            items.append(parse_detail(_get(sess, card["url"], delay), card["url"], card))
        except Exception as e:
            log.warning("HKUBS 상세 실패 %s: %s", card["url"], e)
    log.info("HKUBS: %d건 (HKU 한정 의심 %d건)", len(items),
             sum(i["target"].startswith("[HKU 한정?]") for i in items))
    return items
