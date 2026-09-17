# -*- coding: utf-8 -*-
"""캠퍼스픽(에브리커리어, campuspick.com) 국내 대학생 공모전 수집 — HTML 파싱.

URL 구조 (2026-07 실측):
  - 목록:  https://www.campuspick.com/contest
           Vue CSR 페이지지만 <div id="seo-fallback">에 최신 24건이 SSR로 들어있다.
           `?page=2`는 200을 주지만 seo-fallback 내용이 1페이지와 완전히 동일하다
           (page 파라미터 무효) → 24건보다 더 필요하면 sitemap.xml에서 id를 얻는다.
  - 확장:  https://www.campuspick.com/sitemap.xml  (/contest/view?id= URL 2000건,
           문서 순서가 id 내림차순 = 최신순. 마감 지난 공고도 포함된다.)
  - 상세:  https://www.campuspick.com/contest/view?id={id}

본문은 CSS 셀렉터로 못 뽑는다. 상세 DOM은 CSR이라 div#seo-fallback이 비어 있고,
공고 원문은 <script id="__INITIAL_STATE__" type="application/json">의
activity.description(순수 평문, HTML 태그·네비게이션 0건)에 들어있다.

내부 JSON API(api2.campuspick.com/find/activity/list)는 인증 없이 동작하지만
api2 호스트의 robots.txt가 `Disallow: /` 라서 쓰지 않는다. www 쪽 robots.txt는
/contest, /contest/view, /sitemap.xml 을 모두 허용한다(2026-07 실측).
"""
import re
import time
import html
import json
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

log = logging.getLogger("campuspick")

BASE = "https://www.campuspick.com"
LIST_URL = f"{BASE}/contest"
SITEMAP_URL = f"{BASE}/sitemap.xml"
DETAIL_URL = f"{BASE}/contest/view?id={{id}}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 상세 페이지에서 공고 원문이 들어있는 JSON 스크립트 id
STATE_SCRIPT_ID = "__INITIAL_STATE__"
# 목록 SSR 블록 id
FALLBACK_ID = "seo-fallback"
# 목록/상세 href에서 id 추출
ID_PAT = re.compile(r"/contest/view\?id=(\d+)")
# 응모대상 전용 필드가 없어 본문에서 잘라 쓴다 (아래 _extract_target 주석 참고)
TARGET_HEAD = re.compile(r"(참가\s?자격|응모\s?자격|지원\s?자격|"
                         r"참가\s?대상|응모\s?대상|지원\s?대상)")
# 본문 섹션 머리(줄 첫머리의 글머리표 또는 '4. ') — 참가자격 문단의 끝 표시
SECTION_HEAD = re.compile(r"\n\s*(?:[■○●◎◆◇▶□▷Ο]|\d+\.\s)")


def _get(url: str, delay: float = 1.0) -> str:
    """예의 있는 요청: 요청 간 delay를 두고, 실패 시 1회 재시도."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            time.sleep(delay)
            return r.text
        except Exception as e:
            log.warning("요청 실패(%s/2): %s (%s)", attempt + 1, url, e)
            time.sleep(3)
    raise RuntimeError(f"페이지 요청 실패: {url}")


def list_activity_ids(pages: int = 2, limit: int = 60,
                      delay: float = 1.0) -> list[str]:
    """공모전 상세 id 수집 (최신순).

    pages=1 이면 목록 SSR 24건만. pages>=2 면 sitemap.xml에서 id를 이어붙인다
    (사이트의 ?page= 파라미터가 무효라 페이지네이션 대신 쓰는 경로다).
    """
    ids: list[str] = []
    seen: set[str] = set()

    soup = BeautifulSoup(_get(LIST_URL, delay), "html.parser")
    node = soup.find(id=FALLBACK_ID)
    if node is None:
        log.warning("목록 SSR 블록(#%s) 없음 — sitemap만 사용", FALLBACK_ID)
        node = None
    for a in (node.find_all("a", href=True) if node else []):
        m = ID_PAT.search(a["href"])
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ids.append(m.group(1))
    log.info("목록 SSR: %d건", len(ids))

    if pages > 1 and len(ids) < limit:
        try:
            xml = _get(SITEMAP_URL, delay)
        except Exception as e:
            log.warning("sitemap 요청 실패: %s — 목록 SSR %d건만 사용", e, len(ids))
            return ids[:limit]
        for m in ID_PAT.finditer(xml):   # 문서 순서 = id 내림차순(최신순)
            if m.group(1) in seen:
                continue
            seen.add(m.group(1))
            ids.append(m.group(1))
            if len(ids) >= limit:
                break
        log.info("sitemap 포함 누적: %d건", len(ids))
    return ids[:limit]


def _initial_state(soup: BeautifulSoup) -> dict:
    """상세 HTML의 __INITIAL_STATE__ JSON. 없거나 깨졌으면 빈 dict."""
    tag = soup.find("script", id=STATE_SCRIPT_ID)
    if tag is None:
        return {}
    try:
        data = json.loads(tag.get_text())
    except Exception as e:
        log.warning("__INITIAL_STATE__ JSON 파싱 실패: %s", e)
        return {}
    return data if isinstance(data, dict) else {}


def _clean_date(s) -> str | None:
    """'YYYY-MM-DD' 문자열이면 그대로, 아니면 None (변환 로직 불필요)."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return s


def _extract_target(desc: str) -> str:
    """본문에서 참가자격 문단만 잘라낸다.

    캠퍼스픽 JSON에는 응모대상 전용 필드가 없다(activity.target=1 은 '공모전'
    이라는 콘텐츠 종류 값이지 응모대상이 아니다). 못 찾으면 빈 문자열.
    """
    m = TARGET_HEAD.search(desc or "")
    if not m:
        return ""
    seg = desc[m.end():]
    stop = SECTION_HEAD.search(seg)   # 다음 섹션 머리에서 끊는다
    if stop:
        seg = seg[:stop.start()]
    return re.sub(r"\s+", " ", seg).strip(" :：-·")[:300]


def _host(act: dict) -> str:
    """주최(company) / 주관(company2) / 후원·공동주최(company3) 합치기."""
    names, seen = [], set()
    for key in ("company", "company2", "company3"):
        v = (act.get(key) or "").strip()
        if v and v not in seen:
            seen.add(v)
            names.append(v)
    return " / ".join(names)


def fetch_activity_detail(aid: str, delay: float = 1.0) -> dict:
    """상세 페이지 1건 파싱 → 공통 스키마 dict."""
    url = DETAIL_URL.format(id=aid)
    soup = BeautifulSoup(_get(url, delay), "html.parser")
    state = _initial_state(soup)
    act = state.get("activity") or {}

    title = act.get("title") or ""
    if not title:
        og = soup.find("meta", property="og:title")
        title = (og.get("content") if og and og.get("content") else "")
    # 목록 제목에 &lt; 같은 엔티티가 섞여 있어 unescape 필수
    title = re.sub(r"\s*\|\s*에브리커리어\s*$", "", html.unescape(title)).strip()

    start, end = act.get("start_date") or "", act.get("end_date") or ""
    period = f"{start} ~ {end}" if start and end else (start or end)

    # 분야: 카테고리는 정수 id 배열(예 [101,108])로만 오고 id→이름 매핑표가
    # 공개돼 있지 않다. 추측 매핑 대신 원본 id를 그대로 남긴다.
    cats = [str(c) for c in (state.get("categories") or []) if isinstance(c, int)]
    field = f"공모전 (카테고리 {', '.join(cats)})" if cats else "공모전"

    prize_top = act.get("prize_top")
    prize = f"최고 상금 {prize_top:,}원" if isinstance(prize_top, int) and prize_top else ""

    # region은 값이 없을 때 문자열 'null'로 오는 경우가 있다
    region = str(act.get("region") or "").strip()
    location = "" if region in ("", "null") else region

    body = act.get("description") or ""
    if not body:
        log.warning("본문(__INITIAL_STATE__.activity.description) 없음 — "
                    "요약으로 대체 id=%s", aid)
        body = f"{title} | 분야: {field} | 접수기간: {period}"

    return {
        "source": "캠퍼스픽(국내)",
        "ix": f"campuspick-{act.get('id', aid)}",
        "url": url,
        "homepage": (act.get("website") or "").strip() or url,
        "title": title,
        "field": field,
        "target": _extract_target(body),
        "host": _host(act),
        "period": period,
        "prize": prize,
        "deadline": _clean_date(act.get("end_date")),
        "body": body[:8000],
        "lang": "ko",
        "location": location,
    }


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """국내 대학생 공모전을 최신순으로 수집 → 공통 스키마 dict 리스트."""
    ids = list_activity_ids(pages=pages, limit=max_details)
    results = []
    for aid in ids[:max_details]:
        try:
            results.append(fetch_activity_detail(aid))
        except Exception as e:
            log.warning("상세 파싱 실패 id=%s: %s", aid, e)
    log.info("[캠퍼스픽(국내)] 상세 수집 완료: %d건", len(results))
    return results
