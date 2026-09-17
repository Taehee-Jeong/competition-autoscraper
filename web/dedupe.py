# -*- coding: utf-8 -*-
"""같은 대회가 여러 사이트에 올라온 것을 찾아 하나로 합친다.

정확히 같은 제목은 이미 수집 단계에서 걸러진다(scraper/output.py의 정규화 키).
여기서 다루는 건 **한 단어씩 다른 것** — '대학가요제'/'대학 가요제',
'…학술대회'/'…학술대회 공모전' 같은 것들이라 유사도로 볼 수밖에 없다.

두 개씩 짝지어 보면 안 된다. A≈B, B≈C 처럼 사슬로 엮이는 경우가 실제로 있어서
(경기도 1인가구 공모전이 씽굿·콘테스트코리아·링커리어 셋에 걸쳐 있었다),
먼저 군집으로 묶은 뒤 군집마다 남길 하나를 고른다.
"""
import re
from difflib import SequenceMatcher

from . import db, scoring

DEFAULT_THRESHOLD = 0.85
# 제목이 길면 유사도만으로는 부족하다. 실제로 이런 것들이 같은 대회로 묶였다:
#   [충북] …지원사업(팝업운영)  ↔  …지원사업(국내ㆍ외형)      ← 다른 사업
#   [부산] 중구 FTA 피해보전직불금  ↔  해운대구 수산분야 FTA …  ← 다른 지자체
# 그래서 '다른 글자 수'와 '마감일'을 함께 본다. 같은 대회면 마감일이 같다.
MAX_DIFF_CHARS = 6
_NORM = re.compile(r"[^0-9a-z가-힣]")


def _key(title: str) -> str:
    return _NORM.sub("", str(title or "").lower())


def _diff_chars(a: str, b: str) -> int:
    m = SequenceMatcher(None, a, b)
    return sum(max(i2 - i1, j2 - j1)
               for op, i1, i2, j1, j2 in m.get_opcodes() if op != "equal")


def same_contest(a, b, ka: str, kb: str, threshold: float) -> bool:
    """두 줄이 같은 대회인가. 셋 다 만족해야 한다."""
    if SequenceMatcher(None, ka, kb).ratio() < threshold:
        return False
    if _diff_chars(ka, kb) > MAX_DIFF_CHARS:
        return False                       # 괄호 안 사업명이 다른 경우가 여기서 걸린다
    if a["deadline"] and b["deadline"] and a["deadline"] != b["deadline"]:
        return False                       # 같은 대회면 마감일이 같다
    return True


def pairs(threshold: float = DEFAULT_THRESHOLD) -> list[tuple]:
    """같은 대회로 볼 만한 짝. 길이 차가 큰 것은 아예 비교하지 않는다."""
    rows = db.list_candidates(hide_merged=True)
    keyed = [(r, _key(r["title"])) for r in rows]
    out = []
    for i, (a, ka) in enumerate(keyed):
        if not ka:
            continue
        for b, kb in keyed[i + 1:]:
            if kb and abs(len(ka) - len(kb)) < 12 and same_contest(a, b, ka, kb, threshold):
                out.append((a, b))
    return out


def clusters(threshold: float = DEFAULT_THRESHOLD) -> list[list]:
    """사슬로 엮인 것까지 한 덩어리로 묶는다. → 2개 이상인 군집 목록."""
    parent, rows = {}, {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs(threshold):
        rows[a["id"]], rows[b["id"]] = a, b
        parent[find(a["id"])] = find(b["id"])

    groups = {}
    for rid in rows:
        groups.setdefault(find(rid), []).append(rows[rid])
    return [g for g in groups.values() if len(g) > 1]


def keeper(group: list):
    """군집에서 남길 하나를 고른다.

    점수가 높은 쪽 → 본문이 있는 쪽 → 링크가 있는 쪽 → 먼저 들어온 쪽 순.
    점수에는 판정 근거와 마감 여유가 반영돼 있어서, 대개 정보가 제일 많은 줄이 남는다.
    """
    return max(group, key=lambda r: (scoring.score(r)[0],
                                     bool(r["body"]), bool(r["link"]),
                                     -_ordinal(r["first_seen"])))


def _ordinal(s) -> float:
    try:
        return float(str(s).replace("-", "").replace("T", "").replace(":", ""))
    except ValueError:
        return 0.0


def auto_merge(threshold: float = DEFAULT_THRESHOLD) -> tuple[int, int, list[str]]:
    """군집마다 하나만 남기고 나머지를 합친다. → (합친 건수, 군집 수, 요약 목록).

    사람이 검수를 끝낸 줄은 건드리지 않는다 — 이미 판단한 것을 기계가 숨기면
    왜 사라졌는지 알 수 없다.
    """
    merged, done, notes = 0, 0, []
    for group in clusters(threshold):
        if any(r["decision"] for r in group):
            continue
        keep = keeper(group)
        drops = [r for r in group if r["id"] != keep["id"]]
        if not drops:
            continue
        for r in drops:
            db.merge(r["id"], keep["id"])
            merged += 1
        done += 1
        notes.append(f"{keep['title'][:40]} — {keep['source']} 남기고 "
                     f"{', '.join(r['source'] for r in drops)} 합침")
    return merged, done, notes
