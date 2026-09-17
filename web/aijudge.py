# -*- coding: utf-8 -*-
"""로컬 LLM이 후보를 대신 검수한다 — 사람이 다 보기 힘들 때의 보조 수단.

**AI 판단은 사람 판단 칸에 바로 들어가지 않는다.** ai_reviews에 '제안'으로 남고,
사람이 목록에서 한 번에 적용한다. 적용된 것도 source='ai'로 표시돼 평가셋에는
들어가지 않는다(제 출력으로 제 규칙을 학습하면 안 되므로).

이 모델(qwen2.5:3b)은 하루 사이에 세 번 사고를 쳤다: 프롬프트의 예시를 답으로 베끼고,
근거 없이 부적합을 단정하고, 문자열 자리에 dict를 돌려줬다. 그래서 여기서는
  - 항목 설명을 JSON 값 자리에 넣지 않고
  - 본문에서 그대로 옮긴 근거 문장을 반드시 요구하고
  - 근거가 본문에 실제로 있는지 대조해서 없으면 확신을 낮추고
  - 타입이 어긋나면 '판단보류'로 떨어뜨린다.
"""
import os
import re
import json
import logging

import requests

from . import db

log = logging.getLogger("aijudge")

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

PROMPT = """다음은 공모전/대회 공고입니다. 우리 학교 학생에게 공지할지 판단해 JSON으로만 답하세요.

우리 기준 (셋 다 맞아야 '확정'):
1. 대학 재학생이 참가할 수 있다
2. 팀(2인 이상)으로 참가할 수 있다
3. 신청 마감까지 2주 이상 남았다  ← 이건 이미 걸러졌으니 판단하지 마세요

판단 값:
- 확정: 본문에 재학생·팀 참가가 가능하다는 근거가 있다
- 기각: 본문에 참가할 수 없다는 근거가 있다
- 판단보류: 본문만으로는 알 수 없다

기각 사유는 다음 중 하나입니다: 재학생불가, 팀불가, 분야벗어남

규칙:
- **본문에 적힌 것만 근거로 삼으세요.** 짐작하지 마세요.
- rationale에는 본문에서 그대로 옮긴 문장을 넣으세요. 옮길 문장이 없으면 판단보류입니다.
- confidence는 근거가 명확하면 "높음", 추론이 섞이면 "보통", 애매하면 "낮음"입니다.
- 애매하면 기각하지 말고 판단보류로 두세요. 잘못 버리는 것이 남겨두는 것보다 나쁩니다.

이 틀의 값만 채워서 출력하세요:
{{"decision":"","reason":"","confidence":"","rationale":""}}

공고 제목: {title}
응모대상: {target}
공고 본문:
{body}
"""


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _pick(v, allowed: tuple, default=""):
    """LLM이 준 값에서 앞뒤 공백을 털고 허용 목록과 대조한다.

    실제로 '판단보류' 앞에 공백을 붙여 돌려주는 일이 있었다.
    """
    s = v.strip() if isinstance(v, str) else ""
    return s if s in allowed else default


def _grounded(rationale: str, body: str) -> bool:
    """근거로 든 문장의 낱말이 본문에 실제로 있는지 대충 대조한다.

    작은 모델은 본문을 그대로 옮기지 않고 제 말로 바꿔 쓰므로 문장 일치로는
    잡히지 않는다. 그래서 낱말 단위로 본다 — 지어낸 근거는 본문에 없는 낱말이 많다.
    """
    words = re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", rationale or "")
    if len(words) < 4:
        return False
    nb = _norm(body)
    return sum(1 for w in words if _norm(w) in nb) / len(words) >= 0.6


def judge_one(row) -> dict:
    """한 건 판정. 실패하면 판단보류."""
    body = (row["body"] or "")[:4000]
    if len(body) < 60:
        return {"decision": "판단보류", "confidence": "낮음",
                "rationale": "본문이 없어 판단할 수 없습니다."}
    try:
        r = requests.post(f"{HOST}/api/chat", timeout=120, json={
            "model": MODEL, "stream": False, "format": "json",
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "user", "content": PROMPT.format(
                title=row["title"], target=row["eligibility"] or "명시 없음", body=body)}],
        })
        r.raise_for_status()
        out = json.loads((r.json().get("message") or {}).get("content", ""))
    except Exception as e:
        log.warning("판정 실패(%s): %s", row["title"][:30], e)
        return {"decision": "판단보류", "confidence": "낮음", "rationale": f"판정 실패: {e}"}

    if not isinstance(out, dict):
        return {"decision": "판단보류", "confidence": "낮음", "rationale": "형식 오류"}

    dec = _pick(out.get("decision"), ("확정", "기각", "판단보류"))
    if not dec:
        return {"decision": "판단보류", "confidence": "낮음",
                "rationale": f"알 수 없는 판단: {out.get('decision')!r}"}

    rationale = out.get("rationale") if isinstance(out.get("rationale"), str) else ""
    rationale = rationale.strip()
    conf = _pick(out.get("confidence"), db.AI_CONFIDENCE, "낮음")
    reason = _pick(out.get("reason"), tuple(db.REJECT_REASONS))

    if dec == "기각" and not reason:
        return {"decision": "판단보류", "confidence": "낮음",   # 사유 없는 기각은 받지 않는다
                "rationale": rationale or "기각 사유를 대지 못했습니다."}

    # 지어낸 근거면 확신을 낮춘다. 사람이 '확신 높은 것만' 적용할 때 걸러지도록.
    if dec != "판단보류" and not _grounded(rationale, body):
        conf = "낮음"
        rationale = (rationale + " (근거가 본문에서 확인되지 않음)").strip()

    return {"decision": dec, "reason": reason, "confidence": conf,
            "rationale": rationale[:500]}


def judge_all(redo: bool = False, limit: int = 0, progress=None) -> dict:
    """미검수 후보를 순서대로 판정. → 집계."""
    rows = db.candidates_for_ai(redo=redo)
    if limit:
        rows = rows[:limit]
    tally = {"확정": 0, "기각": 0, "판단보류": 0}
    for i, row in enumerate(rows, 1):
        res = judge_one(row)
        db.set_ai_review(row["id"], res["decision"], res.get("reason", ""),
                         res["confidence"], res.get("rationale", ""))
        tally[res["decision"]] = tally.get(res["decision"], 0) + 1
        if progress:
            progress(i, len(rows), row["title"], res)
    return {"판정": len(rows), **tally}
