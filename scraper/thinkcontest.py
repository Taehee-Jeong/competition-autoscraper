# -*- coding: utf-8 -*-
"""씽굿(thinkcontest.com) 국내 공모전 수집 — 사이트 내부 JSON API 사용.

목록 화면(/thinkgood/user/contest/index.do)의 HTML은 빈 껍데기이고 표는 XHR로
채워진다. 그래서 bs4로 index.do를 긁으면 0건이다. 반드시 아래 POST를 쓴다.

  POST https://www.thinkcontest.com/thinkgood/user/contest/subList.do
  body: {"recordsPerPage":10,"currentPageNo":N,"searchProcess":"ING"}

실측 함정 3가지 (2026-07 확인):
  1) body에 "querystr" 키를 넣으면 무조건 {"status":"0"} 실패.
  2) sidx/sord(정렬)를 같이 보내면 status=1인데 listJsonData가 빈 배열.
  3) recordsPerPage를 20으로 보내도 서버는 항상 10건만 준다 → 페이징은
     currentPageNo로만 한다.

목록 응답이 공모요강 전문(competition_syllabus)까지 주므로 상세 페이지는
받지 않는다 (요청 수 1/10). 로그인·API키 불필요, robots.txt 허용 경로.
"""
import re
import json
import time
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("thinkcontest")

BASE = "https://www.thinkcontest.com"
LIST_API = f"{BASE}/thinkgood/user/contest/subList.do"
VIEW_URL = BASE + "/thinkgood/user/{reg_type}/view.do?contest_pk={pk}"
SOURCE_NAME = "씽굿(국내)"

# Content-Type이 없으면 서버가 JSON 바디를 못 읽는다 (jQuery ajax와 동일하게 보낸다).
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE}/thinkgood/user/contest/index.do",
}

PER_PAGE = 10          # 서버 고정값
MAX_BODY = 8000        # 판정용 본문 길이 상한 (wevity와 동일)

# 본문 필드: 공모요강이 핵심이고 나머지는 보조 설명. 여기 없는 필드는 쓰지 않는다
# (사이트 네비게이션/추천목록이 섞일 여지를 아예 만들지 않기 위함).
BODY_FIELD = "competition_syllabus"
EXTRA_BODY_FIELDS = [("소개", "introduction"), ("기대효과", "effect"),
                     ("심사기준", "standard")]

# 씽굿 내부 편집 흔적이 제목에 그대로 노출되는 건이 있다.
# 예: '중복 // 미디어아트 IP 공모전', '태곤 작성 중 // 2026년 군 인권 홍보콘텐츠 공모전'
TITLE_PREFIX_RE = re.compile(r"^\s*(?:중복|[^/]*작성\s*중)\s*//\s*")


def _strip_html(raw: str) -> str:
    """HTML 조각 → 순수 텍스트 (엔티티 복원 포함). 값이 없으면 빈 문자열."""
    if not raw:
        return ""
    text = BeautifulSoup(str(raw), "html.parser").get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_deadline(item: dict) -> str | None:
    """마감일 → 'YYYY-MM-DD' 또는 None.

    finish_dt('2026-08-31 23:59:00.0')가 1순위, 없으면 receive_period
    ('2026-07-20 ~ 2026-08-31')의 뒤쪽 날짜를 쓴다.
    """
    finish = str(item.get("finish_dt") or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", finish)
    if m:
        return m.group(0)
    period = str(item.get("receive_period") or item.get("receivetime_period") or "")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", period)
    return dates[-1] if dates else None


def _fetch_page(page: int, delay: float = 1.0) -> list[dict]:
    """subList.do 한 페이지 → 원시 아이템 리스트. 실패하면 빈 리스트."""
    payload = {"recordsPerPage": PER_PAGE, "currentPageNo": page,
               "searchProcess": "ING"}
    try:
        r = requests.post(LIST_API, headers=HEADERS, timeout=25,
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("씽굿 목록 API 실패 page=%d: %s", page, e)
        return []
    finally:
        time.sleep(delay)
    if str(data.get("status")) != "1":
        log.warning("씽굿 목록 API status=%s page=%d: %s",
                    data.get("status"), page, data.get("msg"))
        return []
    return data.get("listJsonData") or []


def _build_body(item: dict, title: str, field: str, period: str) -> str:
    """공모요강 전문 → 판정용 본문.

    목록 JSON이 주는 공모요강 HTML만 쓰므로 네비게이션/사이드바/추천목록이
    섞이지 않는다. 공모요강이 비어 있으면 페이지 전체 같은 것으로 폴백하지 않고
    제목·분야·기간 요약으로 대체한다.
    """
    syllabus = _strip_html(item.get(BODY_FIELD))
    if not syllabus:
        log.warning("공모요강(%s) 없음 — 요약으로 대체 contest_pk=%s",
                    BODY_FIELD, item.get("contest_pk"))
        return f"{title} | 분야: {field} | 접수기간: {period}"
    parts = [syllabus]
    for label, key in EXTRA_BODY_FIELDS:
        extra = _strip_html(item.get(key))
        if extra:
            parts.append(f"[{label}] {extra}")
    return "\n\n".join(parts)[:MAX_BODY]


def _to_record(item: dict) -> dict:
    """목록 JSON 아이템 1건 → 공통 스키마 dict."""
    pk = str(item.get("contest_pk") or "").strip()
    reg_type = str(item.get("reg_type") or "contest").strip() or "contest"
    url = VIEW_URL.format(reg_type=reg_type, pk=pk)

    title = TITLE_PREFIX_RE.sub("", str(item.get("program_nm") or "")).strip()
    field = str(item.get("contest_field_nm") or "").strip()
    period = str(item.get("receivetime_period")
                 or item.get("receive_period") or "").strip()
    # host_organ_nm은 '학교/재단/협회' 같은 분류값이라 주최명이 아니다.
    host = " / ".join(p for p in (str(item.get("host_company") or "").strip(),
                                  str(item.get("supervises_company") or "").strip())
                      if p)
    return {
        "source": SOURCE_NAME,
        "ix": f"thinkcontest-{pk}",
        "url": url,
        "homepage": str(item.get("hompage_url") or "").strip() or url,  # 사이트 필드명 오타 그대로
        "title": title,
        "field": field,
        "target": str(item.get("enter_qualified_nm") or "").strip(),
        "host": host,
        "period": period,
        "prize": str(item.get("prize_money") or item.get("award_size_nm") or "").strip(),
        "deadline": _parse_deadline(item),
        "body": _build_body(item, title, field, period),
        "lang": "ko",
        "location": "",
    }


def scrape(pages: int = 2, max_details: int = 30) -> list[dict]:
    """접수중(ING) 공모전 수집 → 공통 스키마 dict 리스트.

    한 페이지 10건 고정이라 pages*10건이 상한이고, max_details로 최종 건수를
    자른다(상세 페이지를 따로 받지 않으므로 목록 상한과 같은 의미다).
    """
    results: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        raw_items = _fetch_page(page)
        if not raw_items:
            break
        for item in raw_items:
            pk = str(item.get("contest_pk") or "").strip()
            if not pk or pk in seen:
                continue
            seen.add(pk)
            try:
                rec = _to_record(item)
            except Exception as e:
                log.warning("아이템 변환 실패 contest_pk=%s: %s", pk, e)
                continue
            if not rec["title"]:
                log.warning("제목 없음 — 건너뜀 contest_pk=%s", pk)
                continue
            results.append(rec)
        log.info("씽굿 %d페이지: 누적 %d건", page, len(results))
        if len(results) >= max_details:
            break
    log.info("[%s] 수집 완료: %d건", SOURCE_NAME, min(len(results), max_details))
    return results[:max_details]
