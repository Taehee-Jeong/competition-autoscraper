# -*- coding: utf-8 -*-
"""iGEM 수집기 테스트 (네트워크 불필요). 픽스처는 2026-09-13 api.igem.org 응답.

실행:  /usr/bin/python3 tests/test_igem.py
"""
import os
import sys
import json
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import igem  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "igem")


def _load(name):
    return json.load(open(os.path.join(FIX, name), encoding="utf-8"))


TIMELINE = _load("timeline_2026.json")
TEAMS = _load("teams_2026_page1.json")["data"]
COMP = next(c for c in _load("competitions_2026.json")["data"] if c["type"] == "igem")


def test_next_registration_deadline_picks_earliest_future():
    # 2026-03-01 기준: Stage I 정규 마감 04-02 가 가장 이른 남은 등록 마감
    assert igem.next_registration_deadline(TIMELINE, date(2026, 3, 1)) == "2026-04-02"
    # 05-01 기준: Stage I 늦은 마감 06-04 (Stage II·로스터 동결은 신규 등록이 아니라 제외)
    assert igem.next_registration_deadline(TIMELINE, date(2026, 5, 1)) == "2026-06-04"
    # Stage I 마감이 다 지난 뒤(06-05~)에는 None
    assert igem.next_registration_deadline(TIMELINE, date(2026, 6, 10)) is None
    assert igem.next_registration_deadline(TIMELINE, date(2026, 9, 13)) is None


def test_build_item_schema_and_hk_teams():
    hk_extra = [{"name": "HKUST", "country": "HKG", "city": "Hong Kong SAR"},
                {"name": "HKU-HongKong", "country": "HKG", "city": "Pok Fu Lam"}]
    it = igem.build_item(COMP, TIMELINE, TEAMS + hk_extra, today=date(2026, 3, 1))
    assert it["title"] == "iGEM Competition 2026"
    assert it["deadline"] == "2026-04-02"
    assert it["lang"] == "en" and it["source"] == "iGEM(국제)"
    assert "Hong Kong teams: 2" in it["body"] and "HKUST team registered" in it["body"]
    assert "HKU-HongKong, HKUST" in it["body"]
    assert "[Registration] Stage I (Registration): 2026-01-16" in it["body"]
    assert it["url"].startswith("https://competition.igem.org/")


def test_build_item_after_registration_closed_keeps_item_with_no_deadline():
    it = igem.build_item(COMP, TIMELINE, TEAMS, today=date(2026, 9, 13))
    assert it["deadline"] is None
    assert "next season" in it["body"].lower()
    assert "Hong Kong teams: 0" in it["body"]


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
