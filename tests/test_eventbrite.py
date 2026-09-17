# -*- coding: utf-8 -*-
"""Eventbrite 홍콩 파서 테스트 (네트워크 불필요).

tests/fixtures/eventbrite/ 에 2026-09-13 실제 페이지에서 뽑은 JSON을 원래의 <script> 블록 형태로
저장해 두었다(페이지 나머지는 잘라냄, 정규식 추출 경로는 그대로 탄다).
  eb_hack_p1.html          /d/hong-kong-sar/hackathon/?page=1 의 __SERVER_DATA__ (17건)
  eb_detail_kids4kids.html  상세 페이지 __NEXT_DATA__ (Kids4Kids Youth Summit 2026)

실행:  /usr/bin/python3 tests/test_eventbrite.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import eventbrite as eb  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "eventbrite")


def _read(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


# ── 목록 ─────────────────────────────────────────────────────────────────
def test_parse_listing_extracts_results():
    rows = eb.parse_listing(_read("eb_hack_p1.html"))
    assert len(rows) == 17
    by_id = {r["eventbrite_event_id"]: r for r in rows}
    r = by_id["1987471349307"]
    assert r["name"] == "Kids4Kids Youth Summit 2026: AI for Social Good"
    assert r["start_date"] == "2026-09-19" and r["start_time"] == "09:30"
    assert r["primary_venue"]["address"]["localized_address_display"] == \
        "33 King Lam Street Lai Chi Kok, Kowloon, KOW"
    assert r["full_description"] in (None, "")   # 목록엔 본문이 없다


def test_parse_listing_without_server_data():
    assert eb.parse_listing("<html><body>nothing</body></html>") == []


def test_listing_keyword_filter_is_narrow():
    rows = eb.parse_listing(_read("eb_hack_p1.html"))
    kept = [r["name"] for r in rows
            if eb.is_competition_text(r["name"], eb._listing_text(r))]
    # 'hackathon' 경로로 받아도 대부분 워크숍·밋업이라 거의 다 떨어져야 한다.
    # 남는 3건 = 제목의 'Pitch' 1건 + 주최자가 'Hackathon' 태그를 단 워크숍 2건(태그도 매칭 대상)
    assert "Founder Hotseat: Pitch Your Startup to Hong Kong Investors & Advisors" in kept
    assert len(kept) == 3, kept
    for junk in ("HackerX - Hong Kong - Employer Ticket - 10/12",
                 "Public Social HackJam", "Kids4Kids Youth Summit 2026: AI for Social Good"):
        assert junk not in kept, junk


# ── 상세 ─────────────────────────────────────────────────────────────────
def test_parse_detail_fields():
    d = eb.parse_detail(_read("eb_detail_kids4kids.html"))
    assert d["host"] == "Kids4Kids Limited 童協基金會"
    assert d["availability_ends"] == "2026-09-19T03:00:00Z"
    assert d["body"].startswith("Turn AI Into Real-World Impact!")
    assert "aged 12–18" in d["body"]
    assert "用 AI 創造有意義的社會影響！" in d["body"]     # 두 번째 text 모듈도 합쳐진다
    assert "<" not in d["body"] and "&nbsp;" not in d["body"]


def test_parse_detail_without_next_data():
    assert eb.parse_detail("<html></html>") == {}


def test_parse_detail_falls_back_to_summary_when_no_modules():
    # Founder Hotseat(2000430005998) 실측: structuredContent.modules 가 [] 이고 요약만 있다
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"context":{"basicInfo":{"summary":"A Founder Institute event.'
            ' Pitch your startup.","organizer":{"name":"Founder Institute"}},'
            '"structuredContent":{"modules":[]},"seo":{}}}}}</script>')
    d = eb.parse_detail(html)
    assert d["body"] == "A Founder Institute event. Pitch your startup."
    assert d["host"] == "Founder Institute" and d["availability_ends"] is None


def test_platform_format_tag_does_not_match():
    # 'Game or Competition'은 Eventbrite 형식 분류라 트리비아 나이트에 다 붙는다 → 무시
    trivia = {"name": "Friends Trivia", "summary": "quiz night",
              "tags": [{"display_name": "Game or Competition"}, {"display_name": "Trivia"}]}
    assert not eb.is_competition_text(trivia["name"], eb._listing_text(trivia))
    # 주최자가 직접 단 태그는 여전히 매칭된다
    tagged = {"name": "AI Bootcamp", "summary": "", "tags": [{"display_name": "Hackathon"}]}
    assert eb.is_competition_text(tagged["name"], eb._listing_text(tagged))


# ── 항목 변환 ─────────────────────────────────────────────────────────────
def test_result_to_item_with_detail():
    res = next(r for r in eb.parse_listing(_read("eb_hack_p1.html"))
               if r["eventbrite_event_id"] == "1987471349307")
    it = eb.result_to_item(res, eb.parse_detail(_read("eb_detail_kids4kids.html")))
    assert it["source"] == "Eventbrite 홍콩(홍콩)"
    assert it["ix"] == "eventbrite-1987471349307"
    assert it["url"].startswith("https://www.eventbrite.") and it["homepage"] == it["url"]
    assert it["title"] == "Kids4Kids Youth Summit 2026: AI for Social Good"
    assert it["host"] == "Kids4Kids Limited 童協基金會"
    assert it["location"] == "33 King Lam Street Lai Chi Kok, Kowloon, KOW"
    assert it["period"] == "2026-09-19 09:30 ~ 2026-09-19 17:00"
    # availabilityEnds 2026-09-19T03:00Z → HKT 11:00 같은 날
    assert it["deadline"] == "2026-09-19"
    assert it["field"].startswith("Education")
    # 목록 summary 가 본문에 없으면 첫 줄로 붙고, 그 뒤에 상세 본문이 온다
    assert it["body"].startswith("Mark your calendars")
    assert "Turn AI Into Real-World Impact!" in it["body"]
    assert len(it["body"]) <= eb.BODY_MAX
    assert it["lang"] == "en"


def test_result_to_item_without_detail_falls_back():
    res = next(r for r in eb.parse_listing(_read("eb_hack_p1.html"))
               if r["eventbrite_event_id"] == "2000430005998")   # Founder Hotseat
    it = eb.result_to_item(res, None)
    assert it["deadline"] == "2026-10-06"          # start_date 폴백
    assert it["host"] == ""
    assert it["body"]                              # summary 폴백
    assert it["title"].startswith("Founder Hotseat")


def test_online_event_location():
    res = {"eventbrite_event_id": "1", "name": "Online Hackathon", "url": "u",
           "is_online_event": True, "start_date": "2026-10-01"}
    assert eb.result_to_item(res, None)["location"] == "Online"


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
