# -*- coding: utf-8 -*-
"""데이콘(dacon.io) AI·데이터 경진대회 수집 — 공개 JSON API + SSR 상세 페이지.

  목록: https://app.dacon.io/api/v1/competition/list?offset=N&range=
  상세: https://dacon.io/competitions/official/{cpt_id}/overview/

인증·쿠키·API키 불필요(2026-07 실측). 목록 API 호스트가 페이지 호스트와 다르다
(app.dacon.io). 페이지 소스의 __NUXT__ state에 있는 newapi.dacon.io 는 404다.

주의점 둘:
  - `range=ing` 은 ClientError를 준다. range는 빈 값으로 보낸다.
  - 응답의 `on_going` 필드는 마감된 대회도 1이라 진행중 판정에 쓸 수 없다.
    마감 판정은 period_end 로만 한다(마감 2주 규칙은 filters.py 담당이므로
    여기서는 마감 임박/경과 건도 버리지 않고 마감일 최신순으로 정렬만 한다).

상세 페이지는 SSR이라 본문이 HTML에 그대로 들어있다. 다만 데스크톱/모바일이
같은 본문을 두 번 렌더링하므로 비어있지 않은 첫 요소 하나만 쓴다.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("dacon")

LIST_API = "https://app.dacon.io/api/v1/competition/list"
DETAIL_URL = "https://dacon.io/competitions/official/{cid}/overview/"
PAGE_SIZE = 15  # offset 단위 (응답도 15건 고정)

# app.dacon.io 는 브라우저 XHR과 동일한 헤더 세트로 확인했다.
API_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://dacon.io",
    "Referer": "https://dacon.io/",
}
PAGE_HEADERS = {
    "User-Agent": API_HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 공고 본문 영역. main 태그를 쓰면 상단 탭(대회안내|데이터|코드 공유|리더보드…)이
# 섞이고 본문이 2번 중복된다. 못 찾으면 전체 텍스트로 폴백하지 않는다.
BODY_SELECTOR = "div.description div.ql-editor"
BODY_MAX = 8000

# 주최/참가자격은 별도 DOM 필드가 없고 본문 안의 대괄호 라벨로만 있다.
# 주최측 자유 서식이라 없는 공고도 흔하다 → 반드시 빈 문자열 폴백.
HOST_RE = re.compile(r"\[\s*주최[^\]]*\]\s*(.*?)(?=\n\s*\[|\Z)", re.S)
TARGET_RE = re.compile(
    r"\[\s*(?:참가\s*자격|참가\s*대상|응모\s*자격|응모\s*대상)[^\]]*\]\s*(.*?)(?=\n\s*\[|\Z)",
    re.S)
LABEL_MAX = 300

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _deadline(period_end: str | None) -> str | None:
    """'2026-08-14 09:59:59' → '2026-08-14'. 형식이 다르면 None."""
    if not period_end or not isinstance(period_end, str):
        return None
    head = period_end.split(" ")[0]
    return head if DATE_RE.match(head) else None


def _label(pattern: re.Pattern, body: str) -> str:
    m = pattern.search(body or "")
    return re.sub(r"\s+", " ", m.group(1)).strip()[:LABEL_MAX] if m else ""


def _fetch_list(offset: int, delay: float) -> list:
    """목록 API 1페이지 → 원시 dict 리스트. 실패하면 빈 리스트."""
    try:
        r = requests.get(LIST_API, headers=API_HEADERS, timeout=25,
                         params={"offset": offset, "range": ""})
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        log.warning("데이콘 목록 API 실패 offset=%d: %s", offset, e)
        return []
    finally:
        time.sleep(delay)
    return payload.get("data") or []


def _fetch_body(cid: str, delay: float) -> str:
    """상세 페이지에서 공고 본문만 추출. 실패하면 빈 문자열."""
    try:
        r = requests.get(DETAIL_URL.format(cid=cid), headers=PAGE_HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.warning("상세 요청 실패 cpt_id=%s: %s", cid, e)
        return ""
    finally:
        time.sleep(delay)
    # 데스크톱/모바일 중복 렌더링 + 빈 에디터가 섞여 있다 → 첫 비어있지 않은 것만
    for node in soup.select(BODY_SELECTOR):
        text = node.get_text("\n", strip=True)
        if text:
            return text
    return ""


def _to_item(raw: dict) -> dict:
    """목록 API 아이템 1건 → 공통 스키마 dict (본문은 아직 비어있음)."""
    cid = raw.get("cpt_id")
    url = DETAIL_URL.format(cid=cid)
    start, end = raw.get("period_start") or "", raw.get("period_end") or ""
    return {
        "source": "데이콘(국내)",
        "ix": f"dacon-{cid}",
        "url": url,
        "homepage": url,
        "title": (raw.get("name") or raw.get("name_eng") or "").strip(),
        "field": (raw.get("keyword") or "AI·데이터 경진대회").strip(),
        "target": "",
        "host": "",
        "period": f"{start} ~ {end}".strip(" ~"),
        "prize": (raw.get("prize_info") or "").strip(),
        "deadline": _deadline(end),
        "body": "",
        "lang": "ko",
        "location": "",  # API에 장소 필드 없음 (온라인 대회)
    }


def scrape(pages: int = 2, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """데이콘 경진대회 수집 → 공통 스키마 dict 리스트.

    목록 정렬이 날짜순이 아니라 노출 순서라, 마감일 최신순으로 다시 정렬한 뒤
    앞에서 max_details건만 상세 본문을 받는다(상세 1건이 ~900KB라 아낀다).
    """
    raws: list[dict] = []
    seen: set[str] = set()
    for page in range(pages):
        rows = _fetch_list(page * PAGE_SIZE, delay)
        if not rows:
            break
        for raw in rows:
            cid = str((raw or {}).get("cpt_id") or "")
            if cid and cid not in seen:
                seen.add(cid)
                raws.append(raw)
        log.info("데이콘 목록 offset=%d: 누적 %d건", page * PAGE_SIZE, len(raws))

    # 마감일 없는 건은 뒤로 보낸다
    raws.sort(key=lambda x: _deadline(x.get("period_end")) or "", reverse=True)

    results: list[dict] = []
    for raw in raws[:max_details]:
        try:
            item = _to_item(raw)
        except Exception as e:
            log.warning("항목 파싱 실패 cpt_id=%s: %s", (raw or {}).get("cpt_id"), e)
            continue
        if not item["title"]:
            continue
        body = _fetch_body(raw.get("cpt_id"), delay)
        if body:
            item["body"] = body[:BODY_MAX]
            item["host"] = _label(HOST_RE, body) or "데이콘"
            item["target"] = _label(TARGET_RE, body)
        else:
            # 본문 셀렉터 실패 시 페이지 전체 텍스트로 폴백하면 탭 메뉴가 섞인다
            log.warning("본문(%s) 없음 — 요약으로 대체 ix=%s", BODY_SELECTOR, item["ix"])
            item["body"] = (f"{item['title']} | {item['field']} | "
                            f"접수 {item['period'] or '기간 미상'}")
            item["host"] = "데이콘"
        results.append(item)
    log.info("[데이콘(국내)] 수집 완료: %d건", len(results))
    return results
