# -*- coding: utf-8 -*-
"""
K-스타트업 창업지원포털(k-startup.go.kr) 사업공고 스크래퍼.

URL 구조 (2026-07 기준 실제 확인):
  - 목록:  https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do
           ?schM=&page={page}&pbancClssCd=PBC010&pbancEndYn=N   (pbancEndYn=N → 접수중)
  - 상세:  https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do
           ?schM=view&pbancSn={pbancSn}&pbancEndYn=N

목록 li.notice 안의 `javascript:go_view(178642)` 에서 pbancSn을 뽑아 상세로 간다.
서버사이드 렌더링이라 JS 실행·로그인·API키 모두 불필요하다.

주의: 프록시 구간에서 간헐적으로 연결이 끊기므로(_get) 재시도가 필수다.
공모전 전용 사이트가 아니라 창업 '지원사업'이 대부분이고 공모전이 섞여 들어온다.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("kstartup")

BASE = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
LIST_URL = BASE + "?schM=&page={page}&pbancClssCd=PBC010&pbancEndYn=N"
DETAIL_URL = BASE + "?schM=view&pbancSn={sn}&pbancEndYn=N"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BASE,
}

# 상세 공고 본문 영역 (2026-07 실측). 이 div 안에는 상단 메뉴·좌측 사이드바·푸터가
# 전혀 들어있지 않다(#contentViewHtml 1,484자 vs 페이지 전체 4,019자). 셀렉터를
# 안 쓰면 '사업소개'·'고객센터'·'개인정보처리방침' 같은 네비게이션이 전부 섞인다.
BODY_SELECTOR = "#contentViewHtml"

# 상세 정보표(라벨/값) 실측 라벨: 지원분야, 대상연령, 기관구분, 담당부서, 지역,
# 접수기간, 주관기관명, 대상, 창업업력, 연락처
INFO_ROW_SELECTOR = "div.information_box-wrap li.dot_list div.table_inner"

GO_VIEW_RE = re.compile(r"go_view\((\d+)\)")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 상금 전용 필드가 없어 본문에서 긁는다 (실측: '상금 총 1,100만원 및 도전응원금')
PRIZE_RE = re.compile(r"[^\n]{0,30}(?:총\s*상금|상금\s*총|시상\s*규모|시상금|상금)[^\n]{0,70}")
PRIZE_AMOUNT_RE = re.compile(r"\d[\d,]*\s*(?:억|천만|백만|만)?\s*원")
PRIZE_HEAD_RE = re.compile(r"총\s*상금|상금\s*총|시상\s*규모|시상금")
# '누적상금 2천만원을 초과하여 받은 자' 같은 참가 제외 조건이 첫 매치로 잡히는 것을 막는다
PRIZE_NEG_RE = re.compile(r"제외|초과|받은\s*자|불가")
# 목록 하단 span.list 중 주관기관이 아닌 것들
LIST_META_PREFIX = ("등록일자", "시작일자", "마감일자", "조회")


def _get(url: str, delay: float = 1.0) -> BeautifulSoup:
    """예의 있는 요청: 요청 간 delay를 두고, 실패 시 재시도(총 3회)."""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            if not r.encoding:
                r.encoding = "utf-8"
            time.sleep(delay)
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning("요청 실패(%s/3): %s (%s)", attempt + 1, url, e)
            time.sleep(4)
    raise RuntimeError(f"페이지 요청 실패: {url}")


def _detect_lang(title: str) -> str:
    """제목의 알파벳 비율로 판정. 대부분 한글이지만 영문 공고도 섞인다."""
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return "ko"
    ascii_ratio = sum(1 for c in letters if c.isascii()) / len(letters)
    return "en" if ascii_ratio > 0.8 else "ko"


def _last_iso_date(text: str) -> str | None:
    """'2026-07-21 ~ 2026-08-20 16:00' → '2026-08-20'. 못 찾으면 None."""
    found = ISO_DATE_RE.findall(text or "")
    return found[-1] if found else None


def _pick_prize(body: str) -> str:
    """본문에서 상금 문구를 고른다. 금액이 적힌 줄을 최우선.

    첫 매치를 그냥 쓰면 '누적상금 2천만원을 초과하여 받은 자(팀)' 같은 참가
    제외 조건이 상금으로 둔갑한다(실측 pbancSn=178464). 못 찾으면 빈 문자열.
    """
    best, best_score = "", 0
    for hit in PRIZE_RE.finditer(body):
        text = hit.group(0).strip(" ·|")
        score = (3 if PRIZE_AMOUNT_RE.search(text) else 0) \
            + (1 if PRIZE_HEAD_RE.search(text) else 0) \
            - (4 if PRIZE_NEG_RE.search(text) else 0)
        if score > best_score:
            best, best_score = text, score
    return best


def _parse_list_item(li) -> dict | None:
    """목록 li.notice 1개 → 요약 dict. pbancSn을 못 뽑으면 None."""
    a = li.find("a", href=GO_VIEW_RE)
    if not a:
        return None
    m = GO_VIEW_RE.search(a.get("href", ""))
    if not m:
        return None
    sn = m.group(1)

    tit = li.select_one("p.tit")
    title = tit.get_text(" ", strip=True) if tit else ""

    # span.flag 중 D-day(.day)가 아닌 것이 지원분야 (예: '판로ㆍ해외진출')
    field = ""
    for flag in li.select("span.flag"):
        if "day" not in (flag.get("class") or []):
            field = flag.get_text(" ", strip=True)
            break

    # div.bottom span.list = [제목 반복, 주관기관, 등록일자 …, 시작일자 …, 마감일자 …, 조회 …]
    metas = [s.get_text(" ", strip=True) for s in li.select("div.bottom span.list")]
    host = ""
    for text in metas:
        if text and text != title and not text.startswith(LIST_META_PREFIX):
            host = text
            break

    start = end = ""
    for text in metas:
        hit = ISO_DATE_RE.search(text)
        if not hit:
            continue
        if text.startswith("시작일자"):
            start = hit.group(0)
        elif text.startswith("마감일자"):
            end = hit.group(0)

    return {
        "sn": sn,
        "title": title,
        "field": field,
        "host": host,
        "period": f"{start} ~ {end}".strip(" ~"),
        "deadline": end or None,
    }


def _list_announcements(pages: int) -> list[dict]:
    """목록 페이지에서 접수중 공고 요약을 수집 (페이지당 15건 고정)."""
    items: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        try:
            soup = _get(LIST_URL.format(page=page))
        except Exception as e:
            log.warning("목록 %d페이지 실패: %s", page, e)
            break
        rows = soup.select("li.notice")
        if not rows:
            log.warning("목록 %d페이지에 li.notice 없음 — 중단", page)
            break
        for li in rows:
            try:
                item = _parse_list_item(li)
            except Exception as e:
                log.warning("목록 항목 파싱 실패 page=%d: %s", page, e)
                continue
            if item and item["sn"] not in seen:
                seen.add(item["sn"])
                items.append(item)
        log.info("목록 %d페이지: 누적 %d건", page, len(items))
    return items


def _fetch_detail(listed: dict) -> dict:
    """상세 페이지 1건 파싱 → 공통 스키마 dict."""
    sn = listed["sn"]
    url = DETAIL_URL.format(sn=sn)
    soup = _get(url)

    node = soup.select_one(BODY_SELECTOR)

    fields: dict[str, str] = {}
    title = listed.get("title", "")
    body = ""
    if node is None:
        # 전체 텍스트로 폴백하면 네비게이션·푸터가 통째로 섞여 판정을 망친다.
        log.warning("본문 영역(%s) 없음 — 요약으로 대체 pbancSn=%s", BODY_SELECTOR, sn)
    else:
        for tag in node.find_all(["script", "style"]):
            tag.decompose()
        h3 = node.select_one("div.title_wrap h3")
        if h3:
            title = h3.get_text(" ", strip=True) or title
        for row in node.select(INFO_ROW_SELECTOR):
            label = row.select_one("p.tit")
            value = row.select_one("p.txt")
            if label and value:
                key = label.get_text(" ", strip=True)
                if key and key not in fields:
                    fields[key] = value.get_text(" ", strip=True).replace("\xa0", " ")
        body = node.get_text("\n", strip=True)

    period = fields.get("접수기간", "") or listed.get("period", "")
    field = fields.get("지원분야", "") or listed.get("field", "")
    if not body:
        body = f"{title} | 분야: {field} | 접수기간: {period}"

    # 대상: '대상'(일반기업/대학생 등) + '대상연령'. 세부 자격은 본문 '신청대상'에 있다.
    target_parts = []
    for part in (fields.get("대상", ""), fields.get("대상연령", "")):
        if part and part not in target_parts:
            target_parts.append(part)
    target = " / ".join(target_parts)

    # 마감일: 목록의 '마감일자'가 이미 ISO라 가장 깨끗하고, 없을 때만 접수기간에서 뽑는다.
    deadline = listed.get("deadline") or _last_iso_date(period)
    if deadline and not ISO_DATE_RE.fullmatch(deadline):
        deadline = None

    prize = _pick_prize(body)

    return {
        "source": "K-스타트업(국내)",
        "ix": f"kstartup-{sn}",
        "url": url,
        # 외부 공식 홈페이지 링크가 없다(신청도 k-startup 내부 시스템) → 상세 URL을 그대로 쓴다.
        "homepage": url,
        "title": title,
        "field": field,
        "target": target,
        "host": fields.get("주관기관명", "") or listed.get("host", ""),
        "period": period,
        "prize": prize[:200],
        "deadline": deadline,
        "location": fields.get("지역", ""),
        "body": body[:8000],
        "lang": _detect_lang(title),
    }


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """접수중 창업지원 공고를 수집 → 공통 스키마 dict 리스트."""
    listed = _list_announcements(pages=pages)
    results: list[dict] = []
    for row in listed[:max_details]:
        try:
            results.append(_fetch_detail(row))
        except Exception as e:
            log.warning("상세 파싱 실패 pbancSn=%s: %s", row.get("sn"), e)
    log.info("[K-스타트업] 상세 수집 완료: %d건", len(results))
    return results
