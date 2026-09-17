# -*- coding: utf-8 -*-
"""HKU 경영대(HKUBS) 대회 목록 파서 테스트 (네트워크 불필요).

tests/fixtures/hkubs/ 에 2026-09-13 실제 페이지를 저장해 두고 그 위에서 파싱을 검증한다.
  list_upcoming.html   ?timing=upcoming (열린 카드 2개)
  list_archived.html   ?timing=archived (마감 카드 12개, 전부 '(Closed)')
  detail_natixis.html  Natixis 상세

실행:  /usr/bin/python3 tests/test_hkubs.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import hkubs  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hkubs")
NATIXIS_URL = ("https://ug.hkubs.hku.hk/competition/"
               "natixis-cib-global-markets-institute-investment-strategy-challenge-2026")


def _read(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


# ── 목록 ─────────────────────────────────────────────────────────────────
def test_list_upcoming_cards():
    cards = hkubs.list_cards(_read("list_upcoming.html"))
    assert len(cards) == 2, len(cards)
    by_title = {c["title"]: c for c in cards}
    nat = by_title["Natixis CIB Global Markets Institute – Investment Strategy Challenge 2026"]
    assert nat["url"] == NATIXIS_URL
    assert nat["deadline"] == "2026-09-20" and not nat["closed"]
    gw = by_title["Gateway to Tomorrow - Business Case Competition 2026"]
    # 'Deadline: 20 Sep 2026 HKT23:59' → 시각은 버리고 홍콩 현지 날짜만
    assert gw["deadline_text"] == "20 Sep 2026 HKT23:59"
    assert gw["deadline"] == "2026-09-20"
    assert gw["location"] == "Hong Kong"


def test_list_archived_cards_are_marked_closed():
    cards = hkubs.list_cards(_read("list_archived.html"))
    assert len(cards) == 12, len(cards)
    assert all(c["closed"] for c in cards)
    by_title = {c["title"]: c for c in cards}
    # '(Closed)' 표시가 붙어도 날짜·장소는 그대로 읽힌다
    assert by_title["BOCHK Challenge 2026"]["deadline"] == "2026-06-15"
    assert by_title["Deloitte Tax Championship 2026"]["deadline"] == "2026-06-15"
    assert by_title["Deloitte Tax Championship 2026"]["location"] == "Hong Kong & Mainland China"
    # scrape()가 쓰는 필터: 마감 카드는 전부 걸러진다
    assert [c for c in cards if not c["closed"]] == []


def test_split_info():
    info = hkubs._split_info(["Deadline: 10 Sep 2026 HKT23:00 (Closed)", "Location: Hong Kong"])
    assert info == {"deadline_text": "10 Sep 2026 HKT23:00", "location": "Hong Kong",
                    "closed": True}


# ── 상세 ─────────────────────────────────────────────────────────────────
def test_detail_fields():
    d = hkubs.parse_detail(_read("detail_natixis.html"), NATIXIS_URL)
    assert d["source"] == "HKU경영대 대회목록(홍콩)"
    assert d["ix"] == "hkubs-natixis-cib-global-markets-institute-investment-strategy-challenge-2026"
    assert d["title"] == "Natixis CIB Global Markets Institute – Investment Strategy Challenge 2026"
    assert d["deadline"] == "2026-09-20"
    assert d["period"] == "Deadline: 20 Sep 2026"
    assert d["host"] == "Natixis CIB Global Markets Institute"      # '[Message from …]'
    assert d["homepage"].startswith("https://natixisgmihk2026.site.digitevent.com/")
    assert d["location"] == "홍콩 (HKU 게시)"
    assert d["lang"] == "en"
    assert "HK$5,000" in d["prize"]


def test_detail_target_carries_eligibility_sentence():
    d = hkubs.parse_detail(_read("detail_natixis.html"), NATIXIS_URL)
    # 홍콩 전체 대학 대상 → HKU 한정 표시가 붙으면 안 된다
    assert not d["target"].startswith("[HKU 한정?]"), d["target"]
    assert "Eligibility for participation" in d["target"]
    assert "Universities in Hong Kong" in d["target"]
    # 인라인 <strong> 때문에 문장이 조각나면 안 된다
    assert "Natixis CIB Global Markets Institute is inviting students graduating" in d["target"]


def test_detail_body_is_announcement_only():
    d = hkubs.parse_detail(_read("detail_natixis.html"), NATIXIS_URL)
    assert d["body"].startswith("To Penultimate and Final Year UG Students,")
    assert "Full-time students enrolled in Bachelor's or Master's Degree Programs" in d["body"]
    assert len(d["body"]) <= 8000
    # 브레드크럼·헤더 메뉴·info-blk 는 본문이 아니다
    for junk in ("Student Enrichment", "Upcoming Competitions", "Deadline: 20 Sep",
                 "Location: Hong Kong", "Search"):
        assert junk not in d["body"], junk


def test_detail_hku_only_marker_and_fallbacks():
    html = """<html><body><main class="page-content"><h1 class="page-title">HKU Case Comp</h1>
    <div class="info-blk"><span class="info-blk__text">Deadline: 15 Jun 2026</span>
    <span class="info-blk__text">Location: Hong Kong</span></div>
    <div class="ckec"><p>Open to <strong>HKU BBA students only</strong>. Apply by 15 Jun 2026.</p>
    <p>Full-time HKU undergraduates may form teams of 3.</p></div></main></body></html>"""
    d = hkubs.parse_detail(html, "https://ug.hkubs.hku.hk/competition/hku-case-comp")
    assert d["target"].startswith("[HKU 한정?] "), d["target"]
    assert "Open to HKU BBA students only" in d["target"]
    assert d["deadline"] == "2026-06-15"
    assert d["homepage"] == d["url"]           # 외부 링크 없으면 상세 URL
    assert d["host"] == ""                     # '[Message from …]' 없음

    # 본문 컨테이너가 없으면 페이지 전체가 아니라 짧은 요약으로 폴백
    d2 = hkubs.parse_detail("<html><body><nav>Home Menu</nav><h1>X</h1></body></html>",
                            "https://ug.hkubs.hku.hk/competition/x",
                            {"title": "X", "deadline_text": "1 Oct 2026", "deadline": "2026-10-01",
                             "location": "Hong Kong"})
    assert d2["body"].startswith("X | deadline: 1 Oct 2026")
    assert "Menu" not in d2["body"]
    assert d2["deadline"] == "2026-10-01"
    assert d2["target"].startswith("확인필요")


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
