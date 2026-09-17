# -*- coding: utf-8 -*-
"""판정 규칙 회귀 테스트 (네트워크 불필요).

실행:  /usr/bin/python3 tests/test_rules.py
       또는  pytest tests/test_rules.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import filters, classify  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- 팀 판정
def test_team_negative_wins_over_positive():
    """'팀 참가 불가' 같은 부정문 안의 '팀 참가'가 긍정 신호로 뒤집히면 안 된다."""
    for body in ["팀 참가 불가. 팀 구성은 허용되지 않습니다.",
                 "개인 참가만 가능하며 팀 접수는 받지 않습니다.",
                 "본 공모전은 개인 참가만 가능합니다.",
                 "individuals only, no teams allowed"]:
        assert filters.check_team({"body": body}) == "탈락", body


def test_team_positive_still_passes():
    for body in ["대학생 및 휴학생, 팀 단위(2~5인) 접수. 사업계획서 제출",
                 "국민 누구나, 개인 또는 팀(4인 이내) 참여",
                 "누구나 참여 가능, 팀별 3인 이상 구성 권장",
                 "Open to the public. Teams of up to 4 members."]:
        assert filters.check_team({"body": body}) == "통과", body


def test_team_unknown_stays_unknown():
    assert filters.check_team({"body": "출품작은 A4 5매 이내로 제출합니다."}) == "확인필요"


# ---------------------------------------------------------------- 규칙 검증
def _expect_reject(cfg, why):
    before = filters.get_rules()
    try:
        filters.set_rules(cfg)
    except ValueError:
        assert filters.get_rules() == before, f"거부 후 기존 규칙이 바뀜: {why}"
        return
    raise AssertionError(f"거부되어야 할 규칙이 통과함: {why}")


def test_set_rules_rejects_bad_config():
    _expect_reject({"team_pos": ["(?P<bad"]}, "컴파일 불가 정규식")
    _expect_reject({"team_pos": "문자열"}, "리스트가 아님")
    _expect_reject({"team_pos": [123]}, "문자열이 아닌 원소")
    _expect_reject({"team_pos": ["가" * (filters.MAX_PATTERN_LEN + 1)]}, "패턴 길이 초과")
    _expect_reject({"team_pos": ["가"] * (filters.MAX_PATTERNS_PER_LIST + 1)}, "패턴 개수 초과")
    _expect_reject({"없는키": ["가"]}, "알 수 없는 키")


def test_set_rules_accepts_good_config():
    before = filters.get_rules()
    try:
        filters.set_rules({"team_pos": [r"팀\s*단위"]})
        assert filters.get_rules()["team_pos"] == [r"팀\s*단위"]
    finally:
        filters.set_rules(before)


def test_bad_rules_json_falls_back_to_defaults():
    """main.py 경로: 오염된 rules.json이 있어도 크래시 없이 기본 규칙으로 동작해야 한다."""
    import subprocess
    import tempfile
    bad = {"score": 1.0, "config": {"filters": {"team_pos": ["(?P<bad"]},
                                    "schools": {}}}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rules.json")
        json.dump(bad, open(path, "w", encoding="utf-8"))
        code = (
            "import sys, main;"
            f"main.RULES_JSON = {path!r};"
            "main.load_evolved_rules();"
            "from scraper.filters import check_team;"
            "print(check_team({'body': '팀 단위(2~4인) 접수'}))"
        )
        r = subprocess.run(["/usr/bin/python3", "-c", code], cwd=BASE,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "통과" in r.stdout, r.stdout + r.stderr


# ---------------------------------------------------------------- 학부 분류
def test_school_english_keywords_need_word_boundary():
    """'IT'가 competition/digital/writing 안에서 매치되면 안 된다."""
    cases = [
        ({"title": "Creative Writing Contest", "field": "문학"},
         "School of humanities and social Science"),
        ({"title": "Digital Health Challenge", "field": "바이오"},
         "School of Science"),
        ({"title": "Sustainability Innovation Competition", "field": "환경"},
         "Academy of Interdisciplinary Studies"),
        ({"title": "Global Case Competition", "field": "마케팅"},
         "School of Business Management"),
        ({"title": "MIT Media Lab Open Call", "field": ""}, "미분류"),
    ]
    for item, expected in cases:
        assert classify.classify_school(item) == expected, item["title"]


def test_school_acronyms_still_match():
    assert classify.classify_school(
        {"title": "AI 해커톤", "field": ""}) == "School of Engineering"
    assert classify.classify_school(
        {"title": "공모전", "field": "웹/모바일/IT"}) == "School of Engineering"
    assert classify.classify_school(
        {"title": "SW 개발 경진대회", "field": ""}) == "School of Engineering"
    assert classify.classify_school(
        {"title": "Machine Learning Hackathon", "field": ""}) == "School of Engineering"


def test_set_school_keywords_rejects_bad_input():
    before = {k: list(v) for k, v in classify.SCHOOL_KEYWORDS.items()}
    classify.set_school_keywords({"엉뚱한학부": ["가"]})          # 키 불일치 → 무시
    assert classify.SCHOOL_KEYWORDS == before
    classify.set_school_keywords({k: [123] for k in before})     # 값 불량 → 무시
    assert classify.SCHOOL_KEYWORDS == before


# ---------------------------------------------------------------- 평가셋 회귀
def test_golden_set_no_regression():
    """수정 후에도 평가셋 12건의 판정이 나빠지지 않아야 한다."""
    golden = [json.loads(l) for l in
              open(os.path.join(BASE, "data", "평가셋.jsonl"), encoding="utf-8")]
    wrong = []
    for g in golden:
        item = {"target": g.get("target", ""), "body": g.get("body", "")}
        for key, pred in (("student_ok", filters.check_student(item)),
                          ("team_ok", filters.check_team(item))):
            if pred != "확인필요" and (pred == "통과") != g[key]:
                wrong.append(f"{g['title']} / {key}: {pred}")
    assert not wrong, "오판: " + "; ".join(wrong)


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
