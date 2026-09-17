# -*- coding: utf-8 -*-
"""콘테스트코리아(contestkorea.com) 국내 대회·공모전 수집 — 서버사이드 HTML 파싱.

URL 구조 (2026-07 실측):
  - 목록:  https://www.contestkorea.com/sub/list.php?displayrow=48&int_gbn=1&Txt_bcode=&page={N}
           int_gbn=1 → 대회·공모전, int_gbn=2 → 대외활동. displayrow=48까지 정상 동작.
           목록의 접수기간에는 **연도가 없다**('접수 07.24~08.31') → 마감일은 상세에서만 뽑는다.
  - 상세:  https://www.contestkorea.com/sub/view.php?int_gbn=1&Txt_bcode={bcode}&str_no={str_no}

robots.txt는 'User-agent: *' / 'Allow:/' 뿐이라 두 경로 모두 허용, Crawl-delay 없음(실측).
로그인·API키·JS 렌더링 전부 불필요하지만 연결이 간헐적으로 끊긴다
('Remote end closed connection without response') → 재시도 루프가 필수다.

목록에는 본문도 연도도 없어 항목당 상세 요청 1건이 반드시 필요하므로,
목록 단계에서 '접수중'만 남겨 상세 요청 수를 약 2/3로 줄인다.

<title>이 '정보광장 > 대외활동 전체'로 나오지만 실제 내용은 대회·공모전이다.
title 태그로 분류를 판단하지 말 것.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlunparse

log = logging.getLogger("contestkorea")

BASE = "https://www.contestkorea.com"
SUB_BASE = f"{BASE}/sub/"
LIST_URL = f"{SUB_BASE}list.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

DISPLAY_ROW = 48        # 한 페이지 항목 수 (기본 12, 48까지 실측 확인)
INT_GBN = "1"           # 1 = 대회·공모전 (2 = 대외활동)
OPEN_CONDITION = "접수중"   # 그 외: '접수예정', '마감'

# 목록 항목 (반드시 자식 셀렉터. '.list_style_2 li'로 하면 내부 주최/대상 li까지 잡힌다)
LIST_SELECTOR = "div.list_style_2 > ul > li"

# 상세 본문 영역. .view_cont_area / .left_cont 는 상단 GNB가 섞이므로 쓰면 안 된다.
BODY_CLASS = "view_detail_area"
# 본문 꼬리의 'AI 해시태그' 블록(#대학생 #팀 …)은 자격/팀 판정 정규식을 오염시킨다.
BODY_CUT_MARKER = "AI 해시태그"

# 메타표 라벨 (공백 제거 후 비교. 실제 라벨은 '주최 . 주관'처럼 점·공백이 섞여 있다)
LABEL_HOST = "주최.주관"
LABEL_FIELD = "대표분야"
LABEL_TARGET = "참가대상"
LABEL_PERIOD = "접수기간"
LABEL_PRIZE = "시상내역"
LABEL_LOCATION = "대회지역"


def _get(url: str, delay: float = 1.0) -> BeautifulSoup:
    """예의 있는 요청: 요청 간 delay를 두고, 끊기면 3초 뒤 재시도(최대 3회)."""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            time.sleep(delay)
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning("요청 실패(%s/3): %s (%s)", attempt + 1, url, e)
            time.sleep(3)
    raise RuntimeError(f"페이지 요청 실패: {url}")


def _txt(node, sel: str) -> str:
    """자식 셀렉터 텍스트를 공백 정규화해서 반환 (없으면 빈 문자열)."""
    found = node.select_one(sel)
    return " ".join(found.get_text(" ", strip=True).split()) if found else ""


def _absolute(href: str) -> str:
    """상대경로 'view.php?...' → 절대 URL. www 없는 도메인도 정규화한다."""
    url = urljoin(SUB_BASE, href.strip())
    parts = urlparse(url)
    if parts.netloc and parts.netloc != "www.contestkorea.com":
        parts = parts._replace(netloc="www.contestkorea.com")
    return urlunparse(parts)


def list_open_items(pages: int = 2, int_gbn: str = INT_GBN,
                    bcode: str = "") -> list[dict]:
    """목록 페이지에서 '접수중' 항목의 상세 URL·제목·분야를 수집."""
    items: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        url = (f"{LIST_URL}?displayrow={DISPLAY_ROW}&int_gbn={int_gbn}"
               f"&Txt_bcode={bcode}&page={page}")
        soup = _get(url)
        rows = soup.select(LIST_SELECTOR)
        if not rows:
            log.warning("목록 항목(%s) 없음 page=%d — 중단", LIST_SELECTOR, page)
            break
        for li in rows:
            a = li.select_one(".title a[href]")
            if not a:
                continue
            detail_url = _absolute(a.get("href", ""))
            str_no = (parse_qs(urlparse(detail_url).query).get("str_no") or [""])[0]
            if not str_no or str_no in seen:
                continue
            if _txt(li, ".d-day .condition") != OPEN_CONDITION:
                continue    # 접수예정·마감은 상세를 받지 않는다
            seen.add(str_no)
            items.append({
                "str_no": str_no,
                "url": detail_url,
                "title": _txt(li, ".title .txt"),
                "field": _txt(li, ".title .category"),
            })
        log.info("목록 %d페이지(%d건 중 접수중): 누적 %d건", page, len(rows), len(items))
    return items


def _parse_meta_table(soup: BeautifulSoup) -> dict:
    """상세 상단 메타표(.view_top_area .txt_area table)의 th/td 쌍 → dict.

    키는 공백을 모두 없앤 라벨('주최 . 주관' → '주최.주관')로 정규화한다.
    """
    fields: dict = {}
    for tr in soup.select(".view_top_area .txt_area table tr"):
        for th, td in zip(tr.select("th"), tr.select("td")):
            label = "".join(th.get_text().split())
            value = " ".join(td.get_text().split())
            if label and value and label not in fields:
                fields[label] = value
    return fields


def _parse_deadline(period: str) -> str | None:
    """'2026.07.24 ~ 2026.08.31' → '2026-08-31'. 못 뽑으면 None."""
    if not period:
        return None
    m = re.search(r"[~∼〜–-]\s*(\d{4})\.(\d{1,2})\.(\d{1,2})", period)
    if not m:
        found = re.findall(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", period)
        if not found:
            return None
        m_groups = found[-1]
    else:
        m_groups = m.groups()
    y, mo, d = m_groups
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def fetch_detail(entry: dict) -> dict:
    """상세 페이지 1건 파싱 → 공통 스키마 dict."""
    url = entry.get("url", "")
    soup = _get(url)
    fields = _parse_meta_table(soup)

    title = _txt(soup, ".view_top_area h1") or entry.get("title", "")
    period = fields.get(LABEL_PERIOD, "")
    field = fields.get(LABEL_FIELD, "") or entry.get("field", "")

    # 공식 홈페이지 링크는 href가 javascript:void(0)이고 실제 주소는 val2 속성에 있다.
    home_btn = soup.select_one(".view_top_area a.btn_Homelink")
    homepage = (home_btn.get("val2") or "").strip() if home_btn else ""

    # 본문: 공고 원문만. 네비·사이드바가 섞이는 .view_cont_area/.left_cont는 쓰지 않는다.
    body_node = soup.find("div", class_=BODY_CLASS)
    if body_node is None:
        log.warning("본문 영역(.%s) 없음 — 요약으로 대체 str_no=%s",
                    BODY_CLASS, entry.get("str_no", ""))
        body = f"{title} | 분야: {field} | 접수기간: {period}"
    else:
        body = body_node.get_text("\n", strip=True)
        cut = body.find(BODY_CUT_MARKER)
        if cut > 0:
            body = body[:cut].rstrip()

    return {
        "source": "콘테스트코리아(국내)",
        "ix": f"contestkorea-{entry.get('str_no', '')}",
        "url": url,
        "homepage": homepage or url,
        "title": title,
        "field": field,
        "target": fields.get(LABEL_TARGET, ""),
        "host": fields.get(LABEL_HOST, ""),
        "period": period,
        "prize": fields.get(LABEL_PRIZE, ""),
        "deadline": _parse_deadline(period),
        "location": fields.get(LABEL_LOCATION, ""),
        "body": body[:8000],
        "lang": "ko",
    }


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """접수중인 대회·공모전을 목록에서 고른 뒤 상세를 받아 공통 스키마로 반환."""
    entries = list_open_items(pages=pages)
    results: list[dict] = []
    for entry in entries[:max_details]:
        try:
            results.append(fetch_detail(entry))
        except Exception as e:
            log.warning("상세 파싱 실패 str_no=%s: %s", entry.get("str_no", ""), e)
    log.info("[콘테스트코리아(국내)] 상세 수집 완료: %d건", len(results))
    return results
