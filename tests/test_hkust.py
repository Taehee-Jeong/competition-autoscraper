# -*- coding: utf-8 -*-
"""HKUST 캘린더·창업센터 파서 테스트 (네트워크 불필요).

tests/fixtures/hkust/ 에 2026-09-13 실제 페이지를 저장해 두고 그 위에서 파싱을 검증한다.

실행:  /usr/bin/python3 tests/test_hkust.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import hkust  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hkust")


def _read(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


# ── 영문 날짜 ─────────────────────────────────────────────────────────────
def test_parse_en_date_formats():
    cases = {"12 Sep 2026": "2026-09-12",
             "1 October 2026": "2026-10-01",
             "Oct. 1, 2026": "2026-10-01",
             "October 1st, 2026": "2026-10-01",
             "05 Jul 2026 - 23:59": "2026-07-05",
             "Apply ASAP — spaces are limited": None,
             "": None}
    for raw, want in cases.items():
        assert hkust.parse_en_date(raw) == want, (raw, hkust.parse_en_date(raw))


def test_iso_to_hk_date_converts_utc_to_hkt():
    # 2026-07-05T15:59:59Z 는 홍콩시간 7월 5일 23:59 → 날짜는 7월 5일이어야 한다
    assert hkust.iso_to_hk_date("2026-07-05T15:59:59Z") == "2026-07-05"
    # UTC 16:30 은 홍콩 다음날 00:30
    assert hkust.iso_to_hk_date("2026-07-05T16:30:00Z") == "2026-07-06"
    assert hkust.iso_to_hk_date(None) is None


def test_deadline_from_body_needs_year():
    body = ("Applications for the competition are open April 1 through Oct. 1. "
            "Registration deadline: 30 November 2026.")
    assert hkust.deadline_from_body(body) == "2026-11-30"
    # 연도 없는 날짜만 있으면 추정하지 않는다
    assert hkust.deadline_from_body("Apply by Oct. 1.") is None


# ── 캘린더 ────────────────────────────────────────────────────────────────
def test_calendar_list_extracts_event_slugs_only():
    slugs = hkust.calendar_list_links(_read("cal_list_competition.html"))
    urls = set(slugs)
    for must in ("baylor-new-venture-competition-0", "cathay-hackathon-2026",
                 "hong-kong-social-enterprise-challenge-hksec-2026-27",
                 "2026-he-xianzhao-philosophy-science-essay-prize"):
        assert f"https://calendar.hkust.edu.hk/events/{must}" in urls, must
    # 분류 페이지·RSS는 이벤트가 아니다
    for never in ("competition", "rss", "workshop", "featured-events", "non-hkust"):
        assert f"https://calendar.hkust.edu.hk/events/{never}" not in urls, never
    assert len(slugs) == len(urls), "중복 없이 반환"


def test_calendar_nonhkust_list():
    urls = hkust.calendar_list_links(_read("cal_list_nonhkust.html"))
    assert "https://calendar.hkust.edu.hk/events/cathay-hackathon-2026" in urls
    assert 3 <= len(urls) <= 10


def test_calendar_detail_fields():
    d = hkust.parse_calendar_detail(
        _read("cal_detail_baylor.html"),
        "https://calendar.hkust.edu.hk/events/baylor-new-venture-competition-0")
    assert d["title"] == "Baylor New Venture Competition"
    assert d["event_format"] == "Competition"
    assert "Entrepreneurship Center" in d["host"]
    assert "UG students" in d["target"] and "Alumni" in d["target"]
    assert d["period"] == "2026-04-21 ~ 2026-10-01"
    # 본문에 연도 있는 마감 문구가 없으니 기간 종료일로 폴백
    assert d["deadline"] == "2026-10-01"
    assert d["body"].startswith("The John F. Baugh Center for Entrepreneurship")
    # 메뉴·공유 버튼이 본문에 섞이면 안 된다
    for junk in ("Add to Calendar", "Share", "Event Format", "Recommended For"):
        assert junk not in d["body"], junk
    assert "$50,000" in d["prize"]
    assert d["lang"] == "en"


def test_calendar_detail_rejects_non_competition():
    html = """<html><body><h1>IAS Lecture</h1>
    <div class="field field--name-field-category"><div class="field__label">Event Format</div>
    <div class="field__items"><div class="field__item">Seminar, Lecture, Talk</div></div></div>
    <div class="field--name-body"><p>talk</p></div></body></html>"""
    d = hkust.parse_calendar_detail(html, "https://calendar.hkust.edu.hk/events/x")
    assert d["event_format"] == "Seminar, Lecture, Talk"
    assert not hkust.is_calendar_competition(d)


# ── 창업센터 ──────────────────────────────────────────────────────────────
def test_ec_list_cards():
    cards = hkust.ec_list_cards(_read("ec_list_page0.html"))
    by_title = {c["title"]: c for c in cards}
    assert "HKUST Dream Builder" in by_title
    assert "Cathay Hackathon 2026" in by_title
    assert by_title["HKUST Dream Builder"]["deadline"] == "2026-07-05"
    assert by_title["Cathay Hackathon 2026"]["url"] == \
        "https://ec.hkust.edu.hk/events/cathay-hackathon-2026"
    assert len(cards) >= 9


def test_ec_detail_fields():
    d = hkust.parse_ec_detail(_read("ec_detail_global_hackathon.html"),
                              "https://ec.hkust.edu.hk/events/global-hackathon-2026")
    assert d["title"] == "Global Hackathon 2026"
    assert d["host"] == "AI Tinkerers Hong Kong"
    assert d["deadline"] == "2026-09-12"
    assert d["target"].startswith("Open to HKUST Students")
    assert "functional AI agents" in d["body"]
    for junk in ("Sign In", "Sign Up", "Share event with"):
        assert junk not in d["body"], junk


def test_ec_competition_keyword_filter():
    assert hkust.is_competition_text("Cathay Hackathon 2026", "")
    assert hkust.is_competition_text("Startup World Cup 2026 - Hong Kong Region", "")
    assert not hkust.is_competition_text(
        "Friday Dreamer Series: Turn Passion into Business", "a sharing session")
    assert not hkust.is_competition_text(
        "HKUST Mentorship Network - Welcoming & Kick-off", "networking")


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
