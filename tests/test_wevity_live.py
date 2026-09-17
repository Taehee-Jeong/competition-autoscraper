# -*- coding: utf-8 -*-
"""위비티 본문 추출 통합 테스트 (네트워크 필요, 5건 × 약 15초).

실행:  /usr/bin/python3 tests/test_wevity_live.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import wevity  # noqa: E402
from scraper.filters import check_student, check_team  # noqa: E402

# 좌측 카테고리 메뉴·메일링 폼에만 나오는 문구. body에 이게 있으면 스코프가 샌 것.
NAV_MARKERS = ["공모전전략", "메일링 신청", "응시대상자", "대외활동/서포터즈",
               "드림위즈", "네이밍/슬로건"]


def main(n=5):
    ids = wevity.list_contest_ids(pages=1)
    assert ids, "목록에서 ID를 하나도 못 받음"
    items = []
    for ix in ids[:n]:
        items.append(wevity.fetch_contest_detail(ix))

    fails = []
    for it in items:
        leaked = [m for m in NAV_MARKERS if m in it["body"]]
        if leaked:
            fails.append(f"{it['ix']}: body에 메뉴 텍스트 {leaked}")
        if len(it["body"]) < 80:
            fails.append(f"{it['ix']}: body가 너무 짧음 ({len(it['body'])}자)")
        if not it["title"]:
            fails.append(f"{it['ix']}: 제목 비어있음")

    filled = {k: sum(1 for it in items if it.get(k)) for k in
              ("deadline", "target", "field", "host", "period")}
    print(f"수집 {len(items)}건 / 본문 평균 {sum(len(i['body']) for i in items)//len(items)}자")
    print(f"필드 채워짐: {filled}")
    for it in items:
        print(f"  {it['title'][:34]:<36} D={it['deadline']} "
              f"재학생={check_student(it)} 팀={check_team(it)} 대상={it['target'][:16]}")

    if filled["deadline"] < len(items):
        fails.append(f"마감일 파싱 실패 {len(items)-filled['deadline']}건")
    if filled["target"] < len(items):
        fails.append(f"응모대상 누락 {len(items)-filled['target']}건")
    if filled["period"] < len(items):
        fails.append(f"접수기간 누락 {len(items)-filled['period']}건")

    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("\nOK: 본문에 메뉴 텍스트 없음, 필드 전건 채워짐")
    return 0


if __name__ == "__main__":
    sys.exit(main())
