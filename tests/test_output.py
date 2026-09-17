# -*- coding: utf-8 -*-
"""엑셀 출력·중복 제거 테스트 (네트워크 불필요).

실행:  /usr/bin/python3 tests/test_output.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.output import write_candidates, _dedup_key  # noqa: E402


def _item(title, link=""):
    return {"title": title, "homepage": link, "url": link}


def test_dedup_key_ignores_spacing_and_brackets():
    """사이트마다 다르게 표기되는 같은 대회를 같은 키로 본다."""
    same = [("2026 MBC 대학가요제", "2026 MBC 대학 가요제"),
            ("『제1회 …공모대회』", "제1회 …공모대회"),
            ("Global Hack Week: Agents", "global hack week agents")]
    for a, b in same:
        assert _dedup_key(a) == _dedup_key(b), (a, b)


def test_dedup_key_keeps_different_contests_apart():
    """단어가 다르면 합치지 않는다 (유사도 매칭으로 가면 안 되는 이유)."""
    diff = [("Global Hack Week: Data", "Global Hack Week: Agents"),
            ("…학술대회", "…학술대회 공모전"),
            ("2026 시결 신인상 공모", "2026년 시결 신인상 공모")]
    for a, b in diff:
        assert _dedup_key(a) != _dedup_key(b), (a, b)


def test_cross_source_duplicate_written_once():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        added = write_candidates([
            _item("2026 MBC 대학가요제", "https://a.example/1"),
            _item("2026 MBC 대학 가요제", "https://b.example/2"),   # 같은 대회, 다른 사이트
            _item("Global Hack Week: Data", "https://c.example/3"),
            _item("Global Hack Week: Agents", "https://d.example/4"),  # 다른 대회
        ], path)
        assert added == 3, added
        assert write_candidates([_item("2026 MBC  대학가요제")], path) == 0  # 재실행 시 누적 안 됨


def test_llm_shaped_values_do_not_break_the_write():
    """LLM이 dict·list·숫자를 돌려줘도 저장이 죽으면 안 된다 (26분치 수집이 걸려 있다)."""
    from scraper.classify import _text
    assert _text({"학생부": "3,000만원", "일반부": "4,000만원"}) == "학생부: 3,000만원 / 일반부: 4,000만원"
    assert _text(["1등 500만원", "2등 300만원"]) == "1등 500만원 / 2등 300만원"
    assert _text(None) == "" and _text(True) == "" and _text(3) == "3"

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        added = write_candidates([
            {"title": "dict 상금 대회", "homepage": "https://a/1",
             "prize": {"학생부": "3천만원", "일반부": "4천만원"}},
            {"title": "list 일정 대회", "homepage": "https://a/2",
             "schedule": ["예선 8/1", "본선 9/1"], "fee": 50000},
        ], path)
        assert added == 2, added


def test_blank_link_items_do_not_block_each_other():
    """빈 링크가 중복 키로 들어가면 링크 없는 항목이 서로를 막는다."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        added = write_candidates([_item("대회 가"), _item("대회 나"), _item("대회 다")], path)
        assert added == 3, added


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
