# -*- coding: utf-8 -*-
"""홍콩 개발자 커뮤니티(DoraHacks·GDG HK·AI Tinkerers HK) 파서 테스트 (네트워크 불필요).

tests/fixtures/hk_devcomm/ 에 2026-09-13 실제 응답을 저장해 두고, `today`를 고정해 검증한다.
gdg_event_slim_live.json 의 두 번째 항목(id 999001, 일반 밋업)은 필터 테스트용 합성 데이터다.

실행:  /usr/bin/python3 tests/test_hk_devcomm.py
"""
import os
import sys
import json
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import hk_devcomm as hd  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hk_devcomm")
SCHEMA_KEYS = {"source", "ix", "url", "homepage", "title", "field", "target", "host",
               "period", "prize", "deadline", "body", "lang", "location"}
TODAY = date(2026, 9, 13)


def _read(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


def _json(name):
    return json.loads(_read(name))


def _check_schema(it):
    assert SCHEMA_KEYS <= set(it), SCHEMA_KEYS - set(it)
    assert it["source"] == "홍콩 개발자커뮤니티(홍콩)" and it["lang"] == "en"
    assert it["deadline"] is None or len(it["deadline"]) == 10
    assert len(it["body"]) <= 8000 and it["url"].startswith("https://")


# ── 공통 ──────────────────────────────────────────────────────────────────
def test_competition_regex():
    assert hd.is_competition_text("Eco-AI Hackathon", "")
    assert hd.is_competition_text("Creative Minds Jam #1: Hong Kong", "")
    assert hd.is_competition_text("Startup Pitch Night", "")
    # AI Tinkerers 상투구 'no-pitch networking' 은 대회가 아니다
    assert not hd.is_competition_text("September Meetup", "demos and no-pitch networking")
    assert not hd.is_competition_text("Build with AI: Gemini talks", "awards ceremony and prizes")


# ── DoraHacks ─────────────────────────────────────────────────────────────
def test_dorahacks_hk_filter_and_dates():
    data = _json("dorahacks_hk_search.json")
    # 2026-08-01 기준: Creative Minds Jam(7/22~8/28)은 진행 중, 2024·2025 홍콩 건은 종료
    items = hd.dorahacks_items(data, date(2026, 8, 1))
    unames = [i["ix"] for i in items]
    assert unames == ["dorahacks-creativeminds"], unames
    it = items[0]
    _check_schema(it)
    assert it["url"] == "https://dorahacks.io/hackathon/creativeminds"
    # unix 초 → 홍콩 날짜 (1784649660 = 2026-07-22 00:01 HKT)
    assert it["period"] == "2026-07-22 ~ 2026-08-28"
    # 사전등록·시작일이 모두 지났으니 종료일(제출 마감)
    assert it["deadline"] == "2026-08-28"
    assert it["location"] == "Online"
    # 홍콩이 아닌 건(Virtual DeFi, 싱가포르 IRL 2건)은 검색 응답에 있어도 버린다
    assert "dorahacks-event-contracts" not in unames
    assert "dorahacks-web3-social-good-2026" not in unames


def test_dorahacks_irl_venue_and_prize():
    data = _json("dorahacks_hk_search.json")
    items = hd.dorahacks_items(data, date(2025, 3, 20))
    by = {i["ix"]: i for i in items}
    hh = by["dorahacks-aptos-evermove-2025-hk"]      # venue_city_id 1344982653 로 잡힘
    assert hh["location"].startswith("Hong Kong (")
    assert hh["host"] and hh["host"] != "DoraHacks"
    assert hh["prize"] == "514780 USD"
    assert hh["period"] == "2025-03-19 ~ 2025-04-05"
    assert hh["deadline"] == "2025-03-28"           # 사전등록 마감이 아직 앞에 있으면 그것
    assert "dorahacks-icphackerhouse-hk" not in by  # 2024년 건은 종료


def test_dorahacks_all_past_today():
    assert hd.dorahacks_items(_json("dorahacks_hk_search.json"), TODAY) == []


# ── GDG Hong Kong ─────────────────────────────────────────────────────────
def test_gdg_keeps_hackathon_drops_meetup():
    slim = _json("gdg_event_slim_live.json")
    urls = {e["id"]: e["url"] for e in _json("gdg_event_live.json")["results"]}
    items = hd.gdg_items(slim, TODAY, urls)
    assert [i["ix"] for i in items] == ["gdg-hk-129748"], [i["title"] for i in items]
    it = items[0]
    _check_schema(it)
    assert it["title"].startswith("Eco-AI Hackathon")
    assert it["host"] == "GDG Hong Kong"
    # 2026-09-19T02:00:00Z → 홍콩 9/19 10:00
    assert it["period"] == "2026-09-19 ~ 2026-09-20"
    # 본문의 'Registration Deadline: September 10, 2026' 가 시작일보다 우선
    assert it["deadline"] == "2026-09-10"
    assert it["location"] == "Hong Kong (in person)"
    assert it["url"] == urls[129748] and "/events/details/" in it["url"]
    assert "<p>" not in it["body"] and "Track A" in it["body"]


def test_gdg_falls_back_to_static_url():
    items = hd.gdg_items(_json("gdg_event_slim_live.json"), TODAY)
    assert items[0]["url"] == "https://gdg.community.dev/e/mj6yug/"


# ── AI Tinkerers Hong Kong ────────────────────────────────────────────────
def test_aitinkerers_events_collected_from_ld_json():
    evs = hd.aitinkerers_events(_read("aitinkerers_home.html"))
    names = [e["name"] for e in evs]
    assert "Agents, Everywhere: Bots, Channels, & More — Global Hackathon" in names
    assert "AI Tinkerers Hong Kong: September Meetup with Cyberport and EY" in names
    assert len(names) == len(set(names)) >= 5


def test_aitinkerers_hackathon_kept_meetups_dropped():
    html = _read("aitinkerers_home.html")
    # 2026-09-01 기준: 8/31 밋업은 종료, 9/12 해커톤과 9/29 밋업이 남고 그중 해커톤만 대회
    items = hd.aitinkerers_items(html, date(2026, 9, 1))
    assert [i["title"] for i in items] == \
        ["Agents, Everywhere: Bots, Channels, & More — Global Hackathon"]
    it = items[0]
    _check_schema(it)
    assert it["host"] == "AI Tinkerers Hong Kong"
    assert it["deadline"] == "2026-09-12" and it["period"] == "2026-09-12"
    assert it["location"] == "Hong Kong (Hong Kong)"
    assert it["url"] == "https://hong-kong.aitinkerers.org/p/agents-everywhere-bots-channels-more-global-hackathon"
    # 오늘(9/13) 기준으로는 밋업만 남아 0건
    assert hd.aitinkerers_items(html, TODAY) == []


def test_aitinkerers_detail_body_via_fetch():
    html = _read("aitinkerers_home.html")
    detail = _read("aitinkerers_event_global_hackathon.html")
    calls = []

    def fetch(url):
        calls.append(url)
        return detail if url.endswith("global-hackathon") else ""

    items = hd.aitinkerers_items(html, date(2026, 9, 1), fetch)
    assert len(items) == 1
    body = items[0]["body"]
    # 목록의 200자 요약이 아니라 상세 본문(article.prose)
    assert len(body) > 2000 and "OpenAI" in body and not body.rstrip().endswith("...")
    # 지난 이벤트는 상세를 안 읽는다 (9/1 기준 미래 이벤트 3건: 9/12 해커톤, 9/29·10/12 밋업)
    assert len(calls) == 3, calls


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, "→", e)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("ERROR", name, "→", type(e).__name__, e)
    sys.exit(1 if fails else 0)
