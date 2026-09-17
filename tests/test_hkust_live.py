# -*- coding: utf-8 -*-
"""HKUST 캘린더·창업센터 스모크 테스트 (네트워크 필요, 약 1분).

실행:  /usr/bin/python3 tests/test_hkust_live.py

사이트가 리뉴얼되면 여기서 0건이 나온다. 그러면 tests/fixtures/hkust/ 를 새 페이지로
갈아끼우고 tests/test_hkust.py 부터 다시 맞추면 된다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import hkust  # noqa: E402


def _check(items, name):
    assert items, f"{name}: 0건 — 사이트 구조가 바뀌었을 수 있음"
    for it in items:
        assert it["title"] and it["url"].startswith("https://"), it
        assert it["lang"] == "en" and it["source"], it
        assert len(it["body"]) > 40, ("본문이 너무 짧음", it["title"])
        assert it["deadline"] is None or len(it["deadline"]) == 10, it["deadline"]
    print(f"{name}: {len(items)}건")
    for it in items:
        print(f"  - {it['title'][:50]:50s} 마감 {it['deadline']}  {it.get('location','')}")


def test_calendar_live():
    _check(hkust.scrape_calendar(max_details=8), "캘린더")


def test_ec_live():
    _check(hkust.scrape_ec(pages=1, max_details=8), "창업센터")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    test_calendar_live()
    test_ec_live()
    print("OK")
