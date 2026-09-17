# -*- coding: utf-8 -*-
"""후보 적합도 점수 (0~100)와 그 근거.

**점수를 LLM에게 물어보지 않는다.** 이 모델은 숫자를 지어내고, 지어낸 숫자에
그럴듯한 설명까지 붙인다(초등학생 전용 공모전에 '대학생 참가 가능'이라 쓴 전례).
대신 규칙 판정과 AI 판정을 정해진 배점으로 더한다. 그래야
'왜 이 점수인지'를 사람이 검산할 수 있고, 설명이 사실과 어긋나지 않는다.
"""
from . import db

# 항목별 배점. 합계 100점 만점이 되도록 잡았다.
RUBRIC = {
    "재학생": {"통과": 25, "확인필요": 10, "탈락": 0},
    "팀":     {"통과": 25, "확인필요": 10, "탈락": 0},
}
DEADLINE_BANDS = [(60, 20, "마감까지 두 달 넘게 남음"),
                  (30, 16, "마감까지 한 달 넘게 남음"),
                  (14, 10, "마감까지 2주 이상 남음")]
AI_POINTS = {("확정", "높음"): 30, ("확정", "보통"): 22, ("확정", "낮음"): 14,
             ("기각", "높음"): -30, ("기각", "보통"): -20, ("기각", "낮음"): -10,
             ("판단보류", "높음"): 5, ("판단보류", "보통"): 5, ("판단보류", "낮음"): 5}


def score(row) -> tuple[int, list[str]]:
    """→ (0~100 점수, 근거 문장 목록). row는 db.list_candidates()의 한 행."""
    pts, why = 0, []

    for label, key in (("재학생", "judge_student"), ("팀", "judge_team")):
        verdict = row[key] or "확인필요"
        got = RUBRIC[label].get(verdict, 0)
        pts += got
        if verdict == "통과":
            why.append(f"{label} 참가 가능 근거 있음 (+{got})")
        elif verdict == "확인필요":
            why.append(f"{label} 여부는 공고에 없음 (+{got})")
        else:
            why.append(f"{label} 참가 불가 근거 있음 (+0)")

    left = db.days_left(row["deadline"])
    if left is None:
        why.append("마감일을 못 읽음 (+0)")
    else:
        for days, got, text in DEADLINE_BANDS:
            if left >= days:
                pts += got
                why.append(f"{text} — D-{left} (+{got})")
                break
        else:
            why.append(f"마감이 가까움 — D-{left} (+0)")

    ai, conf = row["ai_decision"], row["ai_confidence"]
    if ai:
        got = AI_POINTS.get((ai, conf), 0)
        pts += got
        sign = f"+{got}" if got >= 0 else str(got)
        why.append(f"AI 판정 {ai}(확신 {conf}) ({sign})")
        if ai != "판단보류" and row["ai_rationale"]:
            if "확인되지 않음" in row["ai_rationale"]:
                pts -= 8
                why.append("AI가 든 근거를 본문에서 확인 못 함 (-8)")
            else:
                pts += 8
                why.append("AI가 든 근거가 본문에 실제로 있음 (+8)")
    else:
        why.append("AI가 아직 안 봄 (+0)")

    if row["auto_status"] == "LLM판정_부적합":
        pts -= 12
        why.append("보강 단계 LLM도 부적합으로 봄 (-12)")

    return max(0, min(100, pts)), why


def grade(pts: int) -> str:
    return "높음" if pts >= 75 else "보통" if pts >= 50 else "낮음"


def summary(row) -> tuple[int, str, str]:
    """→ (점수, 등급, 한 줄 근거). 엑셀·목록에 같이 쓴다."""
    pts, why = score(row)
    return pts, grade(pts), " / ".join(why)
