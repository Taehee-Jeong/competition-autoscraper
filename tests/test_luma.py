# -*- coding: utf-8 -*-
"""Luma 홍콩 API 파서 테스트 (네트워크 불필요).

tests/fixtures/luma/ 에 2026-09-13 실제 API 응답을 저장해 두고 그 위에서 파싱을 검증한다.
  luma_q_hackathon.json       get-paginated-events?query=hackathon (20건)
  luma_evget.json             event/get — 밋업(대회 아님), 본문에 hard_break 포함
  luma_evget_hackathon.json   event/get — BUILD ACROSS Hackathon (evt-LOgFr6oLacUYhjj)

실행:  /usr/bin/python3 tests/test_luma.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import luma  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "luma")


def _load(name):
    return json.load(open(os.path.join(FIX, name), encoding="utf-8"))


def _entry(api_id):
    return next(e for e in _load("luma_q_hackathon.json")["entries"]
                if e["event"]["api_id"] == api_id)


# ── 키워드 필터 ───────────────────────────────────────────────────────────
def test_competition_regex():
    assert luma.is_competition_text("Hong Kong AI Summit: BUILD ACROSS Hackathon", "")
    assert luma.is_competition_text("Emerging Technology Olympiads (ETO) 2026", "")
    assert luma.is_competition_text("Founder Night", "Startups pitch to investors.")
    # hkust.COMPETITION_WORDS 와 달리 award/prize/cup 만으로는 안 걸린다
    assert not luma.is_competition_text("AI Fellowship Hong Kong Chapter Launch", "awards night")
    assert not luma.is_competition_text("ROOT Weekly RUN", "General Learning Hacks")
    assert not luma.is_competition_text("Challenger Deep", "")  # 단어 경계


# ── ProseMirror 평탄화 ────────────────────────────────────────────────────
def test_flatten_prosemirror_blocks_and_hard_breaks():
    text = luma.flatten_prosemirror(_load("luma_evget.json")["description_mirror"])
    lines = text.split("\n")
    assert lines[0] == "AI 工具經常聽到，但到底怎樣用在「投資」上面？"
    # 같은 paragraph 안의 hard_break 두 개 → 줄바꿈, 빈 줄은 접힌다
    assert "🎯 這一晚會講三件事" in lines
    assert "" not in lines
    assert "① 如何建立你的第一個 AI 員工" in text


def test_flatten_prosemirror_headings_and_marks():
    text = luma.flatten_prosemirror(_load("luma_evget_hackathon.json")["description_mirror"])
    assert text.startswith("Where Europe and Asia Meet at the Frontier.")
    # bold/italic 마크가 있는 텍스트 조각도 한 줄로 이어진다
    assert "the hackathon theme is BUILD ACROSS, with students competing in three challenge tracks: Finance, Urbanization and Startup." in text


def test_flatten_prosemirror_garbage():
    assert luma.flatten_prosemirror(None) == ""
    assert luma.flatten_prosemirror({"type": "doc"}) == ""
    assert luma.flatten_prosemirror({"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
        {"type": "paragraph"}]}) == "a"


# ── 항목 변환 ─────────────────────────────────────────────────────────────
def test_entry_to_item_hackathon():
    it = luma.entry_to_item(_entry("evt-LOgFr6oLacUYhjj"), _load("luma_evget_hackathon.json"))
    assert it["source"] == "Luma 홍콩(홍콩)"
    assert it["ix"] == "luma-evt-LOgFr6oLacUYhjj"
    assert it["url"] == "https://luma.com/1v076plc" and it["homepage"] == it["url"]
    assert it["title"] == "Hong Kong AI Summit: BUILD ACROSS Hackathon"
    assert it["host"] == "Erasmus Artificial Intelligence Society"
    assert it["field"] == "AI"
    # 2026-10-03T01:00Z ~ 2026-10-04T08:00Z → HKT 09:00 / 16:00
    assert it["period"] == "2026-10-03 09:00 ~ 2026-10-04 16:00 (HKT)"
    # ticket_types[].valid_end_at 가 전부 None → start_at 의 HKT 날짜
    assert it["deadline"] == "2026-10-03"
    assert it["location"].startswith("United Centre")
    assert it["body"].startswith("Where Europe and Asia Meet at the Frontier.")
    assert len(it["body"]) <= luma.BODY_MAX
    assert it["lang"] == "en"
    assert luma.is_competition_text(it["title"], it["body"])


def test_deadline_prefers_earliest_ticket_end_in_hkt():
    detail = {"description_mirror": None,
              "ticket_types": [{"valid_end_at": None},
                               {"valid_end_at": "2026-09-30T16:30:00.000Z"},   # HKT 10-01 00:30
                               {"valid_end_at": "2026-09-25T15:59:00.000Z"}]}  # HKT 09-25 23:59
    it = luma.entry_to_item(_entry("evt-LOgFr6oLacUYhjj"), detail)
    assert it["deadline"] == "2026-09-25"


def test_entry_without_detail_falls_back_to_summary_body():
    ent = _entry("evt-WaC7IMLJ4GlND8T")   # HackStack: 주소 비공개(full_address None)
    it = luma.entry_to_item(ent, None)
    assert it["title"].startswith("Free AI Hackathon")
    assert it["body"].startswith(it["title"] + " | host:")
    assert it["location"] == "Hong Kong"
    assert it["deadline"] == "2026-09-26"
    assert it["host"]                      # hosts[0].name 또는 calendar.name


def test_online_event_location():
    ent = json.loads(json.dumps(_entry("evt-LOgFr6oLacUYhjj")))
    ent["event"]["location_type"] = "online"
    assert luma.entry_to_item(ent, None)["location"] == "Online"


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
