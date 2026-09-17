# -*- coding: utf-8 -*-
"""HKSTP 이벤트(sitemap 경유) 파서 테스트 (네트워크 불필요).

tests/fixtures/hkstp/ 에 2026-09-13 실제 페이지를 저장해 두고 그 위에서 파싱을 검증한다.
  sitemap_sample.xml          실제 sitemap 중 이벤트 <url> 20여 개 (대회 slug·하위경로·뉴스 포함)
  detail_robocon2026.html     지난 행사, 단일 날짜, Venue 있음, 'Organised by …'
  detail_epic2025.html        지난 행사, 기간, 본문에 'Application deadline: 17 Jun 2025'
  detail_mid_autumn_2026.html 'Featured Events'(진행 중) 라벨 — 대회는 아니지만 상태 판정용

실행:  /usr/bin/python3 tests/test_hkstp.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import hkstp  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hkstp")
EV = "https://www.hkstp.org/en/park-life/news-and-events/events/"


def _read(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


# ── sitemap ───────────────────────────────────────────────────────────────
def test_sitemap_event_urls_only_single_slug_events():
    ev = hkstp.sitemap_event_urls(_read("sitemap_sample.xml"))
    urls = [u for u, _ in ev]
    assert EV + "robocon-hk-contest-2026" in urls
    assert EV + "elevator-pitch-international-competition-2025" in urls
    # 뉴스·하위경로(/events/event/…)·홈은 이벤트 상세가 아니다
    assert not any("/news/" in u for u in urls)
    assert not any("/events/event/" in u for u in urls)
    assert "https://www.hkstp.org/en/" not in urls
    lm = dict(ev)[EV + "robocon-hk-contest-2026"]
    assert lm.startswith("2026-07-21"), lm


def test_competition_urls_filtered_and_sorted_by_lastmod_desc():
    comp = hkstp.competition_urls(_read("sitemap_sample.xml"))
    slugs = [u[len(EV):] for u, _ in comp]
    assert slugs[:3] == ["abu-asia-pacific-robot-contest-2026", "robocon-hk-contest-2026",
                         "hong-kong-medtech-innovation-world-cup-at-wt"], slugs[:3]
    for must in ("iads-developer-hackathon", "epic-2025-grand-finale", "science-park-challenge"):
        assert must in slugs, must
    for never in ("bio-connect-2026", "parentsday2026", "global-mixer-malaysia2026"):
        assert never not in slugs, never
    mods = [l for _, l in comp]
    assert mods == sorted(mods, reverse=True)
    assert len(slugs) == len(set(slugs)), "중복 없이 반환"


# ── 상세 ─────────────────────────────────────────────────────────────────
def test_detail_robocon_fields():
    d = hkstp.parse_detail(_read("detail_robocon2026.html"), EV + "robocon-hk-contest-2026")
    assert d["source"] == "HKSTP(홍콩)"
    assert d["ix"] == "hkstp-robocon-hk-contest-2026"
    assert d["title"] == "Robocon 2026 Hong Kong Contest"
    assert d["period"] == "21 Jun 2026"
    assert d["end_date"] == "2026-06-21"
    assert d["deadline"] == "2026-06-21"          # 본문에 마감 문구 없음 → 행사 시작일
    assert d["location"] == "Grand Hall, Building 12W, Hong Kong Science Park"
    assert d["host"] == "Hong Kong Science and Technology Parks Corporation"
    assert d["status"] == "Past Events"
    assert d["lang"] == "en"
    assert hkstp.is_past(d)


def test_detail_epic_deadline_from_body():
    d = hkstp.parse_detail(_read("detail_epic2025.html"),
                           EV + "elevator-pitch-international-competition-2025")
    assert d["title"] == "Elevator Pitch International Competition 2025"
    assert d["period"] == "17 Mar 2025 - 17 Jun 2025"
    # 'Application deadline:' 과 날짜가 다른 태그에 있어도 마감일을 읽는다 (시작일 3/17 이 아님)
    assert d["deadline"] == "2025-06-17"
    assert d["end_date"] == "2025-06-17"
    assert d["host"] == "HKSTP"                   # 주최 문구 없음
    assert d["location"] == "홍콩 (HKSTP)"        # Venue 행 없음
    assert "USD 100M" in d["prize"]


def test_detail_body_is_main_content_only():
    d = hkstp.parse_detail(_read("detail_robocon2026.html"), EV + "robocon-hk-contest-2026")
    assert d["body"].startswith("Organised by Hong Kong Science and Technology Parks Corporation")
    assert len(d["body"]) <= 8000
    # 메가메뉴·공유버튼·Date/Venue 표는 본문이 아니다
    for junk in ("Share this news", "Rental Spaces", "Career Opportunities", "Ideation Programme",
                 "Past Events", "Venue"):
        assert junk not in d["body"], junk


def test_is_past_uses_label_then_end_date():
    d = hkstp.parse_detail(_read("detail_mid_autumn_2026.html"), EV + "mid-autumn-2026")
    assert d["status"] == "Featured Events"
    assert d["period"] == "4 Sep 2026 - 4 Oct 2026"
    assert d["end_date"] == "2026-10-04"
    assert not hkstp.is_past(d, today="2026-09-13")
    assert hkstp.is_past(d, today="2026-10-05")
    # 라벨이 Past 면 날짜와 무관하게 지난 행사
    assert hkstp.is_past({"status": "Past Events", "end_date": "2999-01-01"}, today="2026-09-13")
    # 날짜를 못 읽으면 남긴다(사람이 확인)
    assert not hkstp.is_past({"status": "", "end_date": None, "deadline": None}, today="2026-09-13")


def test_detail_fallbacks_without_body_container():
    html = """<html><head><title>Fallback Hackathon | HKSTP</title>
    <meta property="og:title" content="Fallback Hackathon"></head>
    <body><nav>Sites Rental Spaces</nav><div class="detail-two-third">
    <div class="title"><div class="tags"><a class="tag">Featured Events</a></div>
    <div class="date">1 Nov 2026 - 2 Nov 2026</div></div></div></body></html>"""
    d = hkstp.parse_detail(html, EV + "fallback-hackathon")
    assert d["title"] == "Fallback Hackathon"      # h1 없음 → og:title
    assert d["period"] == "1 Nov 2026 - 2 Nov 2026"
    assert d["deadline"] == "2026-11-01" and d["end_date"] == "2026-11-02"
    assert d["body"].startswith("Fallback Hackathon | date: 1 Nov 2026")
    assert "Rental Spaces" not in d["body"]
    assert d["host"] == "HKSTP" and d["location"] == "홍콩 (HKSTP)"


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
