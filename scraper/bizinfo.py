# -*- coding: utf-8 -*-
"""기업마당(bizinfo.go.kr) 중소기업·소상공인 지원사업 공고 수집 — 서버사이드 HTML 파싱.

URL 구조 (2026-07 실측):
  - 목록:  https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do   (schEndAt=N → 접수중)
  - 상세:  https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={pblancId}

주의사항 두 가지가 실측으로 확인됐다.
  1) 403이 아니라 500이 함정이다. 목록 폼(form#articleSearchForm)의 hidden input을
     전부 그대로 실어 보내야 200이 오고, 없는 파라미터를 끼워 넣거나 condition을
     비우면 500 에러페이지를 돌려준다. 그래서 LIST_PARAMS를 폼에서 그대로 복사했다.
  2) 본문은 반드시 div.view_cont 만 쓴다. 한 단계 위인 div.support_project_detail은
     해시태그 30여개(#제주 #창업 …)와 첨부파일 목록까지 딸려와 자격 판정 정규식을
     오염시키고, 페이지 전체 텍스트는 당연히 GNB/푸터가 전부 섞인다.

robots.txt(200, 실측)의 Disallow는 /super /upload /html /images /agspa /error
/common /lib /WEB-INF /download /direct_do 뿐이라 /sii/siia/* 는 허용이다.
다만 첨부파일 경로(/download, /webapp/upload)는 금지라 첨부는 건드리지 않는다.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, parse_qs, urlparse

log = logging.getLogger("bizinfo")

BASE = "https://www.bizinfo.go.kr"
LIST_URL = f"{BASE}/sii/siia/selectSIIA200View.do"
DETAIL_URL = f"{BASE}/sii/siia/selectSIIA200Detail.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# form#articleSearchForm 의 hidden input 전체. 하나라도 빠지거나 다른 이름을 넣으면 500.
LIST_PARAMS = {
    "hashCode": "", "rowsSel": "6", "rows": "15", "cpage": "1", "cat": "",
    "schJrsdCodeTy": "", "schWntyAt": "", "schAreaDetailCodes": "",
    "schEndAt": "N",              # 접수중만
    "orderGb": "", "sort": "", "schPblancDiv": "",
    "condition": "searchPblancNm",  # 비우면 500
    "condition1": "AND", "preKeywords": "", "keyword": "",
}

# 공고 본문 영역 (네비게이션·사이드바·해시태그·첨부목록이 섞이지 않는 유일한 노드)
BODY_SELECTOR = "div.view_cont"

# 목록 표의 td 순번: 번호/지원분야/지원사업명/신청기간/소관부처·지자체/사업수행기관/등록일/조회수
TD_FIELD, TD_TITLE, TD_PERIOD, TD_JRSD, TD_ORG = 1, 2, 3, 4, 5

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 응모대상 전용 필드가 없어 '사업개요' 본문에서 뽑는다. 실측상 사업개요 첫 '☞' 줄이
# 대상 문장이고(10건 확인), 라벨 표기('지원대상' 등)는 "자세한 지원대상 공고문 참조"
# 같은 안내문에 더 자주 걸린다 → ☞ 줄을 먼저 보고 없을 때만 라벨 표기로 폴백한다.
TARGET_HINT = re.compile(r"☞[^\n]*(?:기업|스타트업|소상공인|법인|대학생|청년|팀)[^\n]*")
TARGET_PAT = re.compile(
    r"[^\n]*(?:지원\s*대상|신청\s*대상|참가\s*대상|응모\s*대상|모집\s*대상|"
    r"지원\s*자격|신청\s*자격|참가\s*자격)[^\n]*")
PRIZE_PAT = re.compile(r"[^\n]*(?:총\s*상금|상\s*금|시상금|상금\s*규모|부상)[^\n]*")


def _get(url: str, params: dict | None = None, delay: float = 1.0) -> BeautifulSoup:
    """예의 있는 요청: 요청 간 delay를 두고, 실패 시 1회 재시도."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=20)
            r.raise_for_status()
            r.encoding = "utf-8"  # 응답 헤더가 charset=UTF-8 고정 (실측)
            time.sleep(delay)
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning("요청 실패(%s/2): %s (%s)", attempt + 1, url, e)
            time.sleep(3)
    raise RuntimeError(f"페이지 요청 실패: {url}")


def _iso_deadline(period: str) -> str | None:
    """'2026-07-24 ~ 2026-08-14' → '2026-08-14'.

    '모집 완료시' 같은 비날짜 값이 실제로 섞여 있으므로 ISO 형태만 통과시킨다.
    """
    tail = (period or "").split("~")[-1].strip()
    return tail if ISO_DATE.match(tail) else None


def _pblanc_id(href: str) -> str | None:
    """목록 링크의 href에서 pblancId 추출."""
    q = parse_qs(urlparse(urljoin(BASE, href)).query)
    return (q.get("pblancId") or [None])[0]


def list_items(pages: int = 2) -> list[dict]:
    """목록 페이지에서 공고 기본정보(제목/분야/기간/주관/마감)를 수집."""
    items: list[dict] = []
    seen: set[str] = set()
    for cpage in range(1, pages + 1):
        params = dict(LIST_PARAMS, cpage=str(cpage))
        try:
            soup = _get(LIST_URL, params=params)
        except Exception as e:
            log.warning("목록 요청 실패 cpage=%d: %s", cpage, e)
            break
        table = soup.find("table")
        if table is None:
            log.warning("목록 표 없음 cpage=%d", cpage)
            break
        rows = table.find_all("tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue  # 헤더행 등
            try:
                a = tr.find("a", href=re.compile("selectSIIA200Detail.do"))
                pid = _pblanc_id(a["href"]) if a and a.get("href") else None
                if not pid or pid in seen:
                    continue
                cells = [td.get_text(" ", strip=True) for td in tds]
                period = cells[TD_PERIOD]
                host = "/".join(x for x in (cells[TD_ORG], cells[TD_JRSD]) if x)
                seen.add(pid)
                items.append({
                    "ix": f"bizinfo-{pid}",
                    "pblanc_id": pid,
                    "url": f"{DETAIL_URL}?pblancId={pid}",
                    "title": cells[TD_TITLE],
                    "field": cells[TD_FIELD],
                    "period": period,
                    "host": host,
                    "deadline": _iso_deadline(period),
                })
            except Exception as e:
                log.warning("목록 행 파싱 실패 cpage=%d: %s", cpage, e)
        log.info("기업마당 목록 %d페이지: 누적 %d건", cpage, len(items))
        if not items:
            break
    return items


def _extract_labeled(node) -> dict:
    """div.view_cont 안의 span.s_title(라벨) / div.txt(값) 쌍 추출."""
    fields = {}
    for li in node.select("ul > li"):
        label = li.select_one("span.s_title")
        value = li.select_one("div.txt")
        if not label or not value:
            continue
        key = label.get_text(" ", strip=True)
        if key and key not in fields:
            fields[key] = re.sub(r"\s+", " ", value.get_text(" ", strip=True))
    return fields


def fetch_detail(item: dict) -> dict:
    """상세 페이지 1건 파싱 → 목록 정보에 본문/대상/상금/홈페이지 보강."""
    soup = _get(DETAIL_URL, params={"pblancId": item["pblanc_id"]})

    body_node = soup.select_one(BODY_SELECTOR)
    if body_node is None:
        # 전체 텍스트로 폴백하면 GNB/사이드바가 판정을 오염시킨다 → 요약으로 대체.
        log.warning("본문 영역(%s) 없음 — 요약으로 대체 ix=%s", BODY_SELECTOR, item["ix"])
        body = f"{item['title']} | 지원분야: {item['field']} | 신청기간: {item['period']}"
        fields = {}
    else:
        # 원본 텍스트 노드 안에 \r\n + 들여쓰기 탭이 그대로 들어있어 줄 단위로 정리한다.
        body = re.sub(r"[ \t\r]*\n[ \t\r]*", "\n", body_node.get_text("\n", strip=True))
        fields = _extract_labeled(body_node)

    # 제목·분야는 상세가 더 정확하지만, 없으면 목록 값을 유지한다.
    h2 = soup.select_one("div.title_area h2.title")
    title = h2.get_text(" ", strip=True) if h2 else item["title"]
    cat = soup.select_one("div.title_area div.category span")
    field = cat.get_text(" ", strip=True) if cat else item["field"]

    # 응모대상·상금 전용 필드가 없어 본문에서 관용 표기를 찾는다 (없으면 빈 값).
    m = TARGET_HINT.search(body) or TARGET_PAT.search(body)
    target = m.group(0).strip()[:300] if m else ""
    m = PRIZE_PAT.search(body)
    prize = m.group(0).strip()[:200] if m else ""

    # 원문 출처 외부 링크. 없으면 공고 URL로 폴백.
    barogagi = soup.select_one("a#barogagi")
    homepage = (barogagi.get("href") or "").strip() if barogagi else ""
    if not homepage.startswith("http"):
        homepage = item["url"]

    return {
        "source": "기업마당(국내)",
        "ix": item["ix"],
        "url": item["url"],
        "homepage": homepage,
        "title": title,
        "field": field,
        "target": target,
        # 상세 '신청기간'은 '2026.07.22 ~ 2026.08.04' 점 구분자라 ISO인 목록 값을 쓴다.
        "host": fields.get("사업수행기관", "") or item["host"],
        "period": item["period"],
        "prize": prize,
        "deadline": item["deadline"],
        "body": body[:8000],
        "lang": "ko",
    }


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """접수중 지원사업 공고를 최신순으로 수집 → 공통 스키마 dict 리스트."""
    listed = list_items(pages=pages)
    results: list[dict] = []
    for item in listed[:max_details]:
        try:
            results.append(fetch_detail(item))
        except Exception as e:
            log.warning("상세 파싱 실패 ix=%s: %s", item.get("ix"), e)
    log.info("[기업마당(국내)] 상세 수집 완료: %d건", len(results))
    return results
