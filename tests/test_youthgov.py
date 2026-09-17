# -*- coding: utf-8 -*-
"""youth.gov.hk 수집기 테스트 (네트워크 불필요).

tests/fixtures/youthgov/q_*.json 은 2026-09-13 실제 API 응답이다.

실행:  /usr/bin/python3 tests/test_youthgov.py
"""
import os
import sys
import json
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import youthgov  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "youthgov")
TODAY = date(2026, 9, 13)


def _entries(name):
    return json.load(open(os.path.join(FIX, name), encoding="utf-8"))["data"]


def test_is_wanted_filters_locale_deadline_and_noise():
    entries = _entries("q_Competition.json")
    by_title = {e["title"]: e for e in entries}
    # 영문 + 미마감 + 대학생에 의미 있는 대회
    assert youthgov.is_wanted(by_title["Healthy Mobile App Sticker Design Competition"], TODAY)
    # 구민 스포츠 리그·수상작 순회전시는 제외
    sports = [t for t in by_title if "Badminton" in t or "Basketball" in t]
    exhib = [t for t in by_title if t.startswith("Roving Exhibition")]
    assert sports and exhib
    assert not any(youthgov.is_wanted(by_title[t], TODAY) for t in sports + exhib)
    # 중국어 항목은 제외
    zh = dict(by_title["Healthy Mobile App Sticker Design Competition"], locale="tc")
    assert not youthgov.is_wanted(zh, TODAY)
    # 마감 지난 건 제외
    old = dict(by_title["Healthy Mobile App Sticker Design Competition"],
               application_deadline="2026-01-01T16:00:00.000000Z")
    assert not youthgov.is_wanted(old, TODAY)


def test_to_item_schema():
    e = {x["title"]: x for x in _entries("q_Competition.json")}[
        "Healthy Mobile App Sticker Design Competition"]
    it = youthgov.to_item(e)
    assert it["title"] == "Healthy Mobile App Sticker Design Competition"
    assert it["url"].startswith("https://www.youth.gov.hk/en/")
    assert it["deadline"] == "2027-01-22" or it["deadline"] == "2027-01-21"  # UTC 16:00 = HKT 익일 00:00
    assert "Office for Film" in it["host"]
    assert it["lang"] == "en" and it["source"] == "Youth.gov.hk(홍콩)"
    assert len(it["body"]) > 40 and "<" not in it["body"]


def test_deadline_utc_to_hkt():
    # 16:00Z 는 홍콩 자정 → 다음날. 15:59:59Z 는 같은 날 23:59
    assert youthgov._hk_date("2026-09-19T15:59:59.000000Z") == "2026-09-19"
    assert youthgov._hk_date("2026-09-19T16:00:00.000000Z") == "2026-09-20"


def test_contest_query_includes_photo_contest():
    entries = _entries("q_Contest.json")
    titles = [e["title"] for e in entries if youthgov.is_wanted(e, TODAY)]
    assert any("Photo and Short Video Contest" in t for t in titles), titles


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
