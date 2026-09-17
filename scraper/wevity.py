# -*- coding: utf-8 -*-
"""
위비티(wevity.com) 공모전 스크래퍼.

URL 구조 (2026-07 기준 실제 확인):
  - 목록:  https://www.wevity.com/?c=find&s=1&gub=2&cidx=5&mode=ing&gp={page}
           (gub=2&cidx=5 → 응시대상 '대학생', mode=ing → 접수중)
  - 상세:  https://www.wevity.com/?c=find&s=1&gbn=view&gp=1&ix={id}
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, parse_qs, urlparse

log = logging.getLogger("wevity")

BASE = "https://www.wevity.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 상세 페이지 정보 라벨 (위비티 상세 화면의 필드명)
DETAIL_LABELS = ["분야", "응모대상", "주최/주관", "후원/협찬", "접수기간",
                 "심사발표", "총 상금", "1등 상금", "홈페이지", "첨부파일"]

# 공고 영역 클래스 (2026-07 실측). 페이지 전체 텍스트를 판정에 쓰면 좌측 메뉴의
# "공모전전략"·"응시대상자 … 대학생 … 청소년"이 정규식에 걸려, 자격 언급이 전혀
# 없는 공고까지 '통과'로 나온다. 못 찾으면 경고 후 전체 페이지로 폴백한다.
INFO_CLASS = "cd-area"      # 분야/응모대상/접수기간/상금/홈페이지 라벨 목록
DESC_CLASS = "comm-desc"    # 상세내용(공모요강) 본문


def _get(url: str, delay: float = 1.0) -> BeautifulSoup:
    """예의 있는 요청: 요청 간 delay를 두고, 실패 시 1회 재시도."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            time.sleep(delay)
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning("요청 실패(%s/2): %s (%s)", attempt + 1, url, e)
            time.sleep(3)
    raise RuntimeError(f"페이지 요청 실패: {url}")


def list_contest_ids(pages: int = 3, mode: str = "ing",
                     gub: str = "2", cidx: str = "5") -> list[str]:
    """목록 페이지에서 공모전 ix ID 수집.

    마크업 클래스에 의존하지 않고 href의 `gbn=view` + `ix=` 패턴만 사용
    → 사이트 리뉴얼에 상대적으로 강함.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for gp in range(1, pages + 1):
        url = f"{BASE}?c=find&s=1&gub={gub}&cidx={cidx}&mode={mode}&gbn=list&gp={gp}"
        soup = _get(url)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "gbn=view" not in href or "ix=" not in href:
                continue
            q = parse_qs(urlparse(urljoin(BASE, href)).query)
            ix = (q.get("ix") or [None])[0]
            if ix and ix not in seen:
                seen.add(ix)
                ids.append(ix)
        log.info("목록 %d페이지: 누적 %d건", gp, len(ids))
    return ids


def _extract_labeled_fields(text: str) -> dict:
    """정보 영역 텍스트에서 '라벨 값' 쌍을 정규식으로 추출.

    영역만 클래스로 좁히고 그 안에서는 라벨 텍스트로 찾으므로,
    <li> 마크업이 바뀌어도 라벨 문구만 유지되면 살아남는다.
    """
    fields = {}
    # 라벨들 사이의 텍스트를 값으로 잡는다. 구분자에 \s를 쓰면 값이 빈 라벨
    # (예: 후원/협찬)이 줄바꿈을 삼켜 다음 줄 전체를 자기 값으로 가져가므로
    # 줄을 넘지 않는 [ \t]만 허용한다.
    label_pat = "|".join(map(re.escape, DETAIL_LABELS))
    for m in re.finditer(
            rf"(?P<label>{label_pat})[ \t]*[:：]?[ \t]*"
            rf"(?P<val>[^\n]+?)(?=(?:{label_pat})[ \t]*[:：]?|\n|$)",
            text):
        label, val = m.group("label"), m.group("val").strip(" ·|")
        if label not in fields and val:
            fields[label] = val[:300]
    return fields


def fetch_contest_detail(ix: str) -> dict:
    """상세 페이지 1건 파싱 → 원시 데이터 dict."""
    url = f"{BASE}?c=find&s=1&gbn=view&gp=1&ix={ix}"
    soup = _get(url)

    # 제목: og:title 우선, 없으면 <title>
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"]
    elif soup.title:
        title = soup.title.get_text()
    title = re.sub(r"\s*-\s*WEVITY.*$", "", title).strip()

    # 정보 영역: cd-area 안의 <li>에 "라벨 값" 형태로 들어있음 → 텍스트 기반 추출
    info_node = soup.find("div", class_=INFO_CLASS)
    if info_node is None:
        log.warning("정보 영역(.%s) 없음 — 페이지 전체에서 라벨 추출 ix=%s", INFO_CLASS, ix)
        info_node = soup
    info_text = "\n".join(li.get_text(" ", strip=True) for li in info_node.find_all("li"))
    fields = _extract_labeled_fields(info_text)

    # 본문(공모요강): 팀 구성/참가비/일정 판단에 필요. 메뉴·사이드바는 제외한다.
    desc_node = soup.find("div", class_=DESC_CLASS)
    if desc_node is None:
        log.warning("본문 영역(.%s) 없음 — 라벨 정보만으로 판정 ix=%s", DESC_CLASS, ix)
        body = info_text
    else:
        body = desc_node.get_text("\n", strip=True)

    # 접수기간 → 마감일. 라벨 값("2026-06-01 ~ 2026-07-30")이 가장 정확하고,
    # 없을 때만 본문에서 찾는다 (본문에는 접수기간 표기가 여러 번 나올 수 있다).
    deadline = None
    m = re.search(r"([\d.\-/]{8,12})\s*[~∼〜–-]\s*([\d.\-/]{8,12})",
                  fields.get("접수기간", "")) or \
        re.search(r"접수기간\s*[:：]?\s*([\d.\-/]{8,12})\s*[~∼〜–-]\s*([\d.\-/]{8,12})", body)
    if m:
        deadline = re.sub(r"[./]", "-", m.group(2)).strip("-")

    return {
        "ix": ix,
        "url": url,
        "title": title,
        "field": fields.get("분야", ""),
        "target": fields.get("응모대상", ""),
        "host": fields.get("주최/주관", ""),
        "period": fields.get("접수기간", ""),
        "prize": fields.get("총 상금", "") or fields.get("1등 상금", ""),
        "homepage": fields.get("홈페이지", ""),
        "deadline": deadline,
        "body": body[:8000],  # LLM/휴리스틱 분석용 본문 일부
    }


def scrape(pages: int = 3, max_details: int = 60,
           gub: str = "2", cidx: str = "5",
           source_name: str = "위비티(국내)") -> list[dict]:
    ids = list_contest_ids(pages=pages, gub=gub, cidx=cidx)
    results = []
    for ix in ids[:max_details]:
        try:
            item = fetch_contest_detail(ix)
            item["source"] = source_name
            item["lang"] = "ko"
            results.append(item)
        except Exception as e:
            log.warning("상세 파싱 실패 ix=%s: %s", ix, e)
    log.info("[%s] 상세 수집 완료: %d건", source_name, len(results))
    return results


def scrape_overseas(pages: int = 2, max_details: int = 30) -> list[dict]:
    """위비티 '해외' 분야 카테고리 (gub=1, cidx=28)."""
    return scrape(pages=pages, max_details=max_details,
                  gub="1", cidx="28", source_name="위비티(해외)")
