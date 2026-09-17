# -*- coding: utf-8 -*-
"""iGEM(국제 합성생물학 대회, igem.org) — 공개 JSON API.

  https://api.igem.org/v1/competitions?year=YYYY            시즌 목록 (type=igem / venture-foundry)
  https://api.igem.org/v1/competitions/<uuid>/timeline      등록·제출·잼버리 일정 (카테고리별)
  https://api.igem.org/v1/teams?year=YYYY&page=N            등록 팀 (20건/페이지, HKG 국가코드로 홍콩 팀 식별)

사이트(competition.igem.org)는 전부 JS SPA라 HTML은 비어 있고, 위 API는 인증 없이 열린다
(2026-09-13 실측). iGEM은 1년에 한 시즌뿐이라 소스 한 번 실행에 후보 1~2건이 나오는 게 정상이다.

마감일: 타임라인의 Stage I(신규 팀 등록) deadline 중 아직 남은 가장 이른 날짜.
등록이 다 끝난 시즌(예: 9월)에는 None으로 두고 본문에 "다음 시즌은 보통 1월 중순 등록 시작"을 적는다
— 이 대회는 학기 초에 팀을 꾸려야 하므로 마감이 지났다고 지우면 안 된다.
"""
import time
import logging
from datetime import date

import requests

log = logging.getLogger("igem")

API = "https://api.igem.org/v1"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}
TEAMS_MAX_PAGES = 40          # 20건/페이지 → 800팀까지 (2026 시즌 463팀)
TYPE_LABEL = {"igem": "iGEM Competition", "venture-foundry": "iGEM Venture Foundry"}


def _session():
    s = requests.Session()
    s.trust_env = False
    s.headers.update(HEADERS)
    return s


def next_registration_deadline(timeline: list, today: date) -> str | None:
    """신규 팀 등록(Stage I) 마감 중 남아 있는 가장 이른 날짜 (없으면 None).

    Stage II(확정)·로스터 동결·잼버리 티켓은 이미 등록한 팀의 일정이라 새로 참가하려는
    학생에게는 마감이 아니다. 이걸 섞으면 9월에 "D-3"로 잡혀 2주 규칙에 걸려 사라진다.
    """
    dates = []
    for cat in timeline or []:
        if cat.get("key") != "registration":
            continue
        for it in cat.get("items", []):
            if not (it.get("label") or "").lower().startswith("stage i "):
                continue
            for ev in it.get("events", []):
                if ev.get("type") == "deadline" and (ev.get("date") or "") >= today.isoformat():
                    dates.append(ev["date"])
    return min(dates) if dates else None


def timeline_summary(timeline: list) -> str:
    """사람이 읽을 일정 요약 (본문용)."""
    lines = []
    for cat in timeline or []:
        for it in cat.get("items", []):
            for ev in it.get("events", []):
                lines.append(f"[{cat.get('label')}] {it.get('label')}: "
                             f"{ev.get('date')} {ev.get('description', '')}".strip())
    return "\n".join(lines)


def hk_teams(teams: list) -> list[dict]:
    return [t for t in teams if t.get("country") == "HKG"
            or "hong kong" in (t.get("city") or "").lower()]


def build_item(comp: dict, timeline: list, teams: list, today: date | None = None) -> dict:
    today = today or date.today()
    year = comp.get("year")
    kind = TYPE_LABEL.get(comp.get("type"), "iGEM")
    title = f"{kind} {year}"
    deadline = next_registration_deadline(timeline, today)
    hk = hk_teams(teams)
    hk_names = ", ".join(sorted(t["name"] for t in hk)) or "(없음)"
    has_hkust = any("HKUST" in t.get("name", "").upper() for t in hk)
    parts = [
        f"iGEM {year} season ({kind}). Registered teams: {len(teams)}, Hong Kong teams: {len(hk)}"
        + (" — HKUST team registered." if has_hkust else "."),
        f"Hong Kong teams: {hk_names}",
        "Eligibility: university students form a team (typically 5-15 undergraduate/postgraduate "
        "students) with faculty PIs; the team registers as an institution team. "
        "Participation is via the HKUST iGEM team — check team recruitment on campus.",
    ]
    if deadline is None:
        parts.append("Registration for this season is closed. The next season's team registration "
                     "usually opens in mid-January; team recruitment on campus happens in the "
                     "preceding fall semester.")
    else:
        parts.append(f"Next registration deadline: {deadline}")
    parts.append("Timeline:\n" + timeline_summary(timeline))
    return {
        "source": "iGEM(국제)",
        "ix": f"igem-{comp.get('uuid', year)}",
        "url": "https://competition.igem.org/registration/overview",
        "homepage": "https://competition.igem.org/",
        "title": title,
        "field": "합성생물학 / 바이오 / 팀 프로젝트",
        "target": "University teams (undergraduate/postgraduate students with PIs); HKUST has a team",
        "host": "iGEM Foundation",
        "period": f"{year} season",
        "prize": "Medals (Gold/Silver/Bronze), Track awards, Grand Prize at Grand Jamboree",
        "deadline": deadline,
        "body": "\n".join(parts)[:8000],
        "lang": "en",
        "location": "Grand Jamboree (해외) + 팀 연구는 HKUST",
        "team_size": "5~15명 팀 (PI 지도교수 포함)",
    }


def scrape(max_details: int = 5, delay: float = 1.0, today: date | None = None) -> list[dict]:
    """현재 연도(그리고 다음 연도가 이미 열렸으면 그것도) iGEM 시즌 → 후보 dict 리스트."""
    today = today or date.today()
    sess = _session()
    items = []
    for year in (today.year, today.year + 1):
        try:
            r = sess.get(f"{API}/competitions", params={"year": year}, timeout=25)
            r.raise_for_status()
            comps = r.json().get("data") or []
        except Exception as e:
            log.warning("iGEM competitions 조회 실패 year=%d: %s", year, e)
            continue
        time.sleep(delay)
        for comp in comps:
            if comp.get("type") != "igem" or comp.get("status") not in ("live", "open", "active"):
                continue
            try:
                r = sess.get(f"{API}/competitions/{comp['uuid']}/timeline", timeout=25)
                r.raise_for_status()
                timeline = r.json()
            except Exception as e:
                log.warning("iGEM timeline 실패 %s: %s", comp.get("uuid"), e)
                timeline = []
            time.sleep(delay)
            teams = []
            for page in range(1, TEAMS_MAX_PAGES + 1):
                try:
                    r = sess.get(f"{API}/teams", params={"year": year, "page": page}, timeout=25)
                    r.raise_for_status()
                    got = r.json().get("data") or []
                except Exception as e:
                    log.warning("iGEM teams 실패 year=%d page=%d: %s", year, page, e)
                    break
                teams.extend(got)
                if len(got) < 20:
                    break
                time.sleep(min(delay, 0.5))
            items.append(build_item(comp, timeline, teams, today))
            log.info("iGEM %d: 팀 %d (홍콩 %d), 다음 등록 마감 %s", year, len(teams),
                     len(hk_teams(teams)), items[-1]["deadline"])
    return items[:max_details]
