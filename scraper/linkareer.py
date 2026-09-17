# -*- coding: utf-8 -*-
"""링커리어(linkareer.com) 국내 공모전 수집 — 공개 GraphQL API 사용.

  POST https://api.linkareer.com/graphql
      filterBy={"activityTypeID":"3","status":"OPEN"}  ← 3 = 공모전, 접수중만

인증·쿠키·API키 없이 200이다(2026-07 실측, currentUser=null 상태로 응답).
Content-Type: application/json 이 필수이고, 브라우저 UA + Origin/Referer를
같이 보낸다. robots.txt는 `Allow: /` 이고 Disallow는 /stem/learn/* 계열뿐이라
목록·상세 모두 허용된다.

목록 응답에 본문(detailText.text)까지 들어있어 상세 페이지 요청이 아예 필요
없다. 이 필드는 공고 본문 HTML 원문이라 네비게이션·사이드바가 섞이지 않는다
(상세 페이지 전체 텍스트를 쓰면 '합격자소서·마이페이지' 같은 메뉴가 딸려온다).

HTML 폴백(/list/contest?page=N 의 __NEXT_DATA__)은 넣지 않았다. 실측해 보니
목록 HTML의 __APOLLO_STATE__ Activity 객체에는 id/title/organizationName/
recruitCloseAt 만 있고 detailText·targets·categories·상금이 없다 — 폴백을
쓰려면 건별 상세 요청이 따로 필요해 사실상 별도 수집기가 된다.
"""
import re
import time
import html
import logging
import requests
from datetime import datetime, timezone, timedelta

log = logging.getLogger("linkareer")

API = "https://api.linkareer.com/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://linkareer.com",
    "Referer": "https://linkareer.com/list/contest",
}

DETAIL_URL = "https://linkareer.com/activity/{}"
ACTIVITY_TYPE_CONTEST = "3"   # 1=대외활동, 3=공모전
PAGE_SIZE = 20
BODY_MAX = 8000

# 서버가 UTC여도 마감일이 하루 밀리지 않도록 KST 고정.
# recruitCloseAt 은 epoch milliseconds (KST 23:59:59.999 시점).
KST = timezone(timedelta(hours=9))

QUERY = ("query L($f:ActivityFilter,$p:Pagination,$o:ActivityOrder){"
         "activities(filterBy:$f,pagination:$p,orderBy:$o){totalCount nodes{"
         "id title organizationName organizationType recruitStartAt "
         "recruitCloseAt tenThousandUnitOfReward homepageURL applyDetail "
         "status targets{id name} categories{id name} detailText{text}}}}")

# 본문 정제용: 블록 태그는 줄바꿈으로 살리고 나머지 태그만 지운다
SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
BLOCK_RE = re.compile(r"</?(p|li|div|br|h[1-6]|tr|ul|ol|table)[^>]*>", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(raw: str) -> str:
    """공고 본문 HTML 조각 → 평문. 비었으면 빈 문자열."""
    if not raw:
        return ""
    text = SCRIPT_RE.sub(" ", raw)
    text = BLOCK_RE.sub("\n", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n", text)
    return text.strip()


def _kst_date(epoch_ms) -> str | None:
    """epoch milliseconds → 'YYYY-MM-DD' (KST). 값이 이상하면 None."""
    if not isinstance(epoch_ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(epoch_ms / 1000, KST).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return None


def _names(nodes) -> str:
    """[{'name':'기획/아이디어'}, ...] → '기획/아이디어, ...'"""
    return ", ".join((n.get("name") or "").strip()
                     for n in (nodes or []) if isinstance(n, dict) and n.get("name"))


def _fetch_page(page: int, delay: float) -> list:
    """목록 1페이지 → 노드 리스트. 실패하면 빈 리스트."""
    payload = {"query": QUERY,
               "variables": {"f": {"activityTypeID": ACTIVITY_TYPE_CONTEST,
                                   "status": "OPEN"},
                             "p": {"page": page, "pageSize": PAGE_SIZE},
                             "o": {"direction": "DESC", "field": "CREATED_AT"}}}
    try:
        r = requests.post(API, headers=HEADERS, json=payload, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("링커리어 GraphQL 실패 page=%d: %s", page, e)
        return []
    finally:
        time.sleep(delay)
    # GraphQL은 에러도 HTTP 200으로 준다
    if data.get("errors"):
        log.warning("링커리어 GraphQL 에러 page=%d: %s", page, data["errors"])
        return []
    activities = (data.get("data") or {}).get("activities") or {}
    return activities.get("nodes") or []


def _to_item(raw: dict) -> dict:
    """API 노드 1건 → 공통 스키마 dict."""
    aid = raw.get("id")
    url = DETAIL_URL.format(aid)
    title = (raw.get("title") or "").strip()
    field = _names(raw.get("categories")) or "공모전"

    start = _kst_date(raw.get("recruitStartAt"))
    deadline = _kst_date(raw.get("recruitCloseAt"))
    period = f"{start} ~ {deadline}" if start and deadline else (deadline or "")

    reward = raw.get("tenThousandUnitOfReward")
    prize = f"{reward}만원" if reward else ""

    org = (raw.get("organizationName") or "").strip()
    org_type = (raw.get("organizationType") or "").strip()
    host = f"{org} ({org_type})" if org and org_type else org

    body = _clean_html(((raw.get("detailText") or {}).get("text")) or "")
    if not body:
        # 본문 필드가 비었을 때 상세 페이지 전체 텍스트로 폴백하지 않는다
        # (메뉴·추천목록이 섞여 자격 판정이 오염된다). 요약으로 대체.
        log.warning("본문(detailText) 없음 — 요약으로 대체 id=%s title=%s", aid, title)
        body = f"{title} | {field} | 접수 {period or '기간 미상'}"

    return {
        "source": "링커리어(국내)",
        "ix": f"linkareer-{aid}",
        "url": url,
        "homepage": raw.get("homepageURL") or raw.get("applyDetail") or url,
        "title": title,
        "field": field,
        "target": _names(raw.get("targets")),
        "host": host,
        "period": period,
        "prize": prize,
        "deadline": deadline,
        "body": body[:BODY_MAX],
        "lang": "ko",
    }


def scrape(pages: int = 2, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """접수중(OPEN) 국내 공모전을 최신순으로 수집 → 공통 스키마 dict 리스트."""
    results: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        if len(results) >= max_details:
            break
        nodes = _fetch_page(page, delay)
        if not nodes:
            break
        for raw in nodes:
            if len(results) >= max_details:
                break
            try:
                item = _to_item(raw)
            except Exception as e:
                log.warning("항목 파싱 실패 id=%s: %s", (raw or {}).get("id"), e)
                continue
            if not item["title"] or not item["ix"] or item["ix"] in seen:
                continue
            seen.add(item["ix"])
            results.append(item)
        log.info("링커리어 %d페이지: 누적 %d건", page, len(results))
    log.info("[링커리어(국내)] 수집 완료: %d건", len(results))
    return results
