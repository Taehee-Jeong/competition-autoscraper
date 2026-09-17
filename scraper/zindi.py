# -*- coding: utf-8 -*-
"""Zindi(zindi.africa) 해외 데이터사이언스 대회 수집 — 비공식 JSON API 사용.

  목록: https://api.zindi.africa/v1/competitions?page=0&per_page=50
  상세: https://api.zindi.africa/v1/competitions/{id}   (id는 슬러그)
  사람이 보는 URL: https://zindi.africa/competitions/{id}

zindi.africa 웹 페이지는 완전 CSR(JS 렌더링)이라 requests+bs4로는 목록 링크가
0개 나온다(2026-07 실측). 그래서 반드시 api.zindi.africa 를 써야 한다.
인증·쿠키·API키 불필요하고 브라우저 User-Agent 하나면 200이다.
robots.txt는 세 호스트 모두 404 = 명시적 Disallow 없음. 비문서 내부 API이므로
스펙 변경 리스크가 있고, 예의상 요청 간 delay를 유지한다.

본문은 상세 응답의 `pages[].content_html`(공고 본문 HTML 조각)에서만 뽑는다.
이 필드에는 네비게이션·사이드바·푸터가 구조적으로 존재하지 않는다.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("zindi")

LIST_API = "https://api.zindi.africa/v1/competitions"
DETAIL_API = "https://api.zindi.africa/v1/competitions/{cid}"
WEB_URL = "https://zindi.africa/competitions/{cid}"

# UA가 유일한 필수 헤더. Accept는 예의상 붙인다.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}

PER_PAGE = 50          # 목록 API 기본값은 10. 접수중 8건은 응답 앞쪽에 몰려 있다.
BODY_MAX = 8000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 응모대상 원문이 담긴 규정 문장 (rules.content.blocks 안의 한 줄)
ELIGIBILITY_PREFIX = "who can compete"


def _iso_date(s) -> str | None:
    """'2026-08-02T23:59:00.000Z' → '2026-08-02'. 형식이 다르면 None."""
    if not s or not isinstance(s, str):
        return None
    head = s[:10]
    return head if DATE_RE.match(head) else None


def _join(*lists) -> str:
    """industry/skills/type_of_problem 등 문자열 리스트들을 콤마로 합친다."""
    out = []
    for lst in lists:
        for v in lst or []:
            v = (v or "").strip() if isinstance(v, str) else ""
            if v and v not in out:
                out.append(v)
    return ", ".join(out)


def _fetch_json(url: str, params: dict | None, delay: float):
    """JSON 1건 요청. 실패하면 None (호출부에서 경고 후 건너뛴다)."""
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("Zindi API 실패 %s: %s", url, e)
        return None
    finally:
        time.sleep(delay)


def _team_line(detail: dict) -> str:
    """팀 참가 가능 여부는 본문 문장이 아니라 구조화 필드에만 있다."""
    mx = detail.get("max_number_of_participants_per_team")
    if not detail.get("allow_teams"):
        return "Individuals only (teams not allowed)"
    if isinstance(mx, int) and mx >= 2:
        return f"Teams of up to {mx} members allowed"
    return "Teams allowed (size not specified)"


def _eligibility_line(detail: dict) -> str:
    """규정 블록에서 'Who can compete: ...' 한 줄을 찾는다. 없으면 빈 문자열."""
    blocks = ((detail.get("rules") or {}).get("content") or {}).get("blocks") or []
    for b in blocks:
        text = (b.get("text") or "").strip() if isinstance(b, dict) else ""
        if text.lower().startswith(ELIGIBILITY_PREFIX):
            return text
    return ""


def _body_text(detail: dict) -> str:
    """pages[].content_html 만 모아 공고 본문 평문으로 만든다.

    각 섹션(Description/Evaluation/Data Description/Prizes/Rules) 앞에
    '== 제목 ==' 헤더를 붙인다. 본문 조각이 하나도 없으면 빈 문자열을 돌려주고,
    호출부가 요약으로 대체한다 (페이지 전체 텍스트로 폴백하지 않는다).
    """
    parts = []
    for p in detail.get("pages") or []:
        if not isinstance(p, dict):
            continue
        raw = p.get("content_html") or ""
        if not raw:
            continue
        text = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)
        if not text:
            continue
        parts.append(f"== {(p.get('title') or '').strip()} ==\n{text}")
    return "\n\n".join(parts)


def _to_item(raw: dict, detail: dict) -> dict:
    """목록 + 상세 응답 1건 → 공통 스키마 dict."""
    cid = raw.get("id") or detail.get("id") or ""
    url = WEB_URL.format(cid=cid)
    title = (detail.get("title") or raw.get("title") or "").strip()

    kind = detail.get("kind") or raw.get("kind") or "competition"
    tags = _join(detail.get("industry"), detail.get("skills"),
                 detail.get("type_of_problem"))
    field = f"{kind} / {tags}" if tags else kind

    eligibility = _eligibility_line(detail)
    team = _team_line(detail)
    target = " / ".join(x for x in (eligibility, team) if x)

    org = (detail.get("organization") or "").strip()
    org_url = (detail.get("organization_url") or "").strip()
    host = f"{org} ({org_url})" if org and org_url else (org or "Zindi")

    start = _iso_date(detail.get("start_time") or raw.get("start_time"))
    deadline = _iso_date(detail.get("end_time") or raw.get("end_time"))
    period = f"{start} ~ {deadline}" if start and deadline else (deadline or "")

    reward = (detail.get("reward") or raw.get("reward") or "").strip()
    rtype = (detail.get("reward_type") or raw.get("reward_type") or "").strip()
    # 'points'는 현금 상금이 아니므로 구분해서 남긴다
    prize = f"{reward} [{rtype}]" if reward and rtype and rtype != "prize" else reward

    location = ", ".join(x for x in ((detail.get("country") or "").strip(),
                                     (detail.get("city") or "").strip()) if x)

    body = _body_text(detail)
    if not body:
        log.warning("본문(pages[].content_html) 없음 — 요약으로 대체 id=%s", cid)
        body = f"{title} | {field} | 접수 {period or '기간 미상'}"
    else:
        # 응모대상·팀 인원은 Rules 섹션(본문 맨 뒤)에 묻혀 있어 판정에서 잘린다.
        # 구조화 필드로 만든 헤더를 앞에 붙여 앞부분만 읽어도 판정되게 한다.
        head = (f"[Eligibility] {eligibility or 'not specified'}\n"
                f"[Team size] {team}\n"
                f"[Location] {location or 'Online (Africa-focused, open worldwide)'}")
        body = f"{head}\n{body}"

    return {
        "source": "Zindi(해외)",
        "ix": f"zindi-{cid}",
        "url": url,
        "homepage": url,
        "title": title,
        "field": field,
        "target": target,
        "host": host,
        "period": period,
        "prize": prize,
        "deadline": deadline,
        "body": body[:BODY_MAX],
        "lang": "en",
        "location": location,
    }


def scrape(pages: int = 2, max_details: int = 30, delay: float = 1.0) -> list[dict]:
    """접수중(open) 대회·해커톤 수집 → 공통 스키마 dict 리스트.

    목록은 최신순이라 open=true 항목이 응답 앞쪽에 몰려 나온다(실측: 498건 중
    접수중 8건이 모두 0~7번). 그래서 open이 하나도 없는 페이지가 나오면
    남은 490건은 전부 마감이므로 더 넘기지 않는다.
    """
    results: list[dict] = []
    seen: set[str] = set()
    for page in range(pages):
        if len(results) >= max_details:
            break
        payload = _fetch_json(LIST_API, {"page": page, "per_page": PER_PAGE}, delay)
        if not payload:
            break
        rows = payload.get("data") or []
        open_rows = [r for r in rows if isinstance(r, dict) and r.get("open")]
        if not open_rows:
            log.info("Zindi %d페이지: 접수중 0건 — 이후는 전부 마감이라 중단", page)
            break
        for raw in open_rows:
            if len(results) >= max_details:
                break
            cid = raw.get("id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            detail = _fetch_json(DETAIL_API.format(cid=cid), None, delay)
            if not detail or not isinstance(detail.get("data"), dict):
                log.warning("상세 응답 이상 — 건너뜀 id=%s", cid)
                continue
            try:
                item = _to_item(raw, detail["data"])
            except Exception as e:
                log.warning("항목 파싱 실패 id=%s: %s", cid, e)
                continue
            if not item["title"]:
                log.warning("제목 없음 — 건너뜀 id=%s", cid)
                continue
            results.append(item)
        log.info("Zindi %d페이지: 누적 %d건", page, len(results))
    log.info("[Zindi(해외)] 수집 완료: %d건", len(results))
    return results
