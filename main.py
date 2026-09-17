# -*- coding: utf-8 -*-
"""컴피티션 자동 리서치 파이프라인.

실행:  python main.py
옵션:  PAGES=5 MAX_DETAILS=80 python main.py
       OLLAMA_MODEL=exaone3.5:2.4b python main.py  ← Ollama 정밀 추출 모델 지정
"""
import os
import sys
import logging
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import (wevity, devpost, thinkcontest, contestkorea, linkareer,
                     campuspick, dacon, unstop, mlh, zindi, drivendata,
                     aicrowd, kstartup, bizinfo, usagov_challenges, hkust,
                     youthgov, igem, hk_devcomm, hk_seeds, hkstp, hkubs, luma,
                     eventbrite)
from scraper.filters import apply_filters
from scraper.classify import enrich
from scraper.output import write_candidates

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_XLSX = os.path.join(BASE, "data", "후보_컴피티션_목록.xlsx")
RULES_JSON = os.path.join(BASE, "data", "rules.json")


def load_evolved_rules():
    """AlphaEvolve 루프가 만든 규칙이 있으면 적용."""
    if not os.path.exists(RULES_JSON):
        return
    try:
        import json
        from scraper import filters, classify
        saved = json.load(open(RULES_JSON, encoding="utf-8"))
        filters.set_rules(saved["config"]["filters"])
        classify.set_school_keywords(saved["config"]["schools"])
        log.info("진화된 규칙 적용 (평가 점수 %.3f)", saved.get("score", 0))
    except Exception as e:
        log.warning("rules.json 적용 실패, 기본 규칙 사용: %s", e)


# 소스 레지스트리: 환경변수 SOURCES로 켜고 끔 (예: SOURCES=wevity,devpost)
SOURCE_REGISTRY = {
    # ── 국내 공모전
    "wevity":       lambda p, m: wevity.scrape(pages=p, max_details=m),
    "wevity_intl":  lambda p, m: wevity.scrape_overseas(pages=max(1, p - 1),
                                                        max_details=m // 2),
    # 씽굿은 한 페이지 10건 고정이라, 원하는 건수를 받으려면 그만큼 페이지를 넘겨야 한다.
    # (서버가 recordsPerPage를 올려 보내도 10건만 준다 — 2026-07 실측)
    "thinkcontest": lambda p, m: thinkcontest.scrape(pages=max(p, -(-m // 10)),
                                                     max_details=m),
    "contestkorea": lambda p, m: contestkorea.scrape(pages=p, max_details=m),
    "linkareer":    lambda p, m: linkareer.scrape(pages=p, max_details=m),
    "campuspick":   lambda p, m: campuspick.scrape(pages=p, max_details=m),
    "dacon":        lambda p, m: dacon.scrape(pages=p, max_details=m),
    # ── 해외
    "devpost":      lambda p, m: devpost.scrape(pages=max(1, p - 1)),
    "unstop":       lambda p, m: unstop.scrape(pages=max(1, p - 1), max_details=m),
    "mlh":          lambda p, m: mlh.scrape(pages=1, max_details=m),
    "zindi":        lambda p, m: zindi.scrape(pages=1, max_details=m),
    "drivendata":   lambda p, m: drivendata.scrape(pages=1, max_details=m),
    "aicrowd":      lambda p, m: aicrowd.scrape(pages=1, max_details=m),
    # ── 홍콩 · HKUST (교내 대회 + HKUST에 게시된 홍콩 외부 대회)
    "hkust_cal":    lambda p, m: hkust.scrape_calendar(pages=1, max_details=m),
    "hkust_ec":     lambda p, m: hkust.scrape_ec(pages=max(1, min(p, 3)), max_details=m),
    "youthgov":     lambda p, m: youthgov.scrape(max_details=m),
    "igem":         lambda p, m: igem.scrape(max_details=m),
    "hk_devcomm":   lambda p, m: hk_devcomm.scrape(pages=p, max_details=m),
    "hk_seeds":     lambda p, m: hk_seeds.scrape(pages=p, max_details=m),
    "hkstp":        lambda p, m: hkstp.scrape(pages=p, max_details=m),
    "hkubs":        lambda p, m: hkubs.scrape(pages=p, max_details=m),
    "luma":         lambda p, m: luma.scrape(pages=p, max_details=m),
    "eventbrite":   lambda p, m: eventbrite.scrape(pages=p, max_details=m),
    "devpost_hk":   lambda p, m: devpost.scrape(pages=5, search="hong kong",
                                                source="Devpost 홍콩(해외)"),
    # ── 공모전이 아니라 '지원사업/과제 공고'라 기본에서 뺐다.
    #    창업·기업지원 쪽을 보고 싶을 때만 SOURCES에 직접 적어서 켜세요.
    "kstartup":     lambda p, m: kstartup.scrape(pages=max(1, p - 1), max_details=m),
    "bizinfo":      lambda p, m: bizinfo.scrape(pages=max(1, p - 1), max_details=m),
    "usagov":       lambda p, m: usagov_challenges.scrape(pages=1, max_details=m),
}
# 모든 소스 기본 활성화 (국내·해외·홍콩 통합 수집)
DEFAULT_SOURCES = "wevity,wevity_intl,thinkcontest,contestkorea,linkareer,campuspick,dacon,devpost,unstop,mlh,zindi,drivendata,aicrowd,hkust_cal,hkust_ec,youthgov,igem,hk_devcomm,hk_seeds,hkstp,hkubs,luma,eventbrite,devpost_hk,kstartup,bizinfo,usagov"

# 화면 표시용 메타 — 웹의 '수집 실행'이 이걸 읽어 체크박스를 만든다.
# 키는 SOURCE_REGISTRY와 같아야 한다 (아래에서 검사한다).
SOURCE_INFO = {
    "wevity":       ("위비티", "국내", "공모전 전 분야 · HTML"),
    "wevity_intl":  ("위비티 해외", "해외", "해외 카테고리 · HTML"),
    "thinkcontest": ("씽굿", "국내", "접수중 860여 건 · API"),
    "contestkorea": ("콘테스트코리아", "국내", "10개 분야 · HTML"),
    "linkareer":    ("링커리어", "국내", "GraphQL"),
    "campuspick":   ("캠퍼스픽", "국내", "대학생 대상 · HTML"),
    "dacon":        ("데이콘", "국내", "AI·데이터 경진 · API"),
    "devpost":      ("Devpost", "해외", "해커톤 · API"),
    "unstop":       ("Unstop", "해외", "공모전·해커톤 · API"),
    "mlh":          ("MLH", "해외", "시즌 해커톤 · API"),
    "zindi":        ("Zindi", "해외", "데이터사이언스 · API"),
    "drivendata":   ("DrivenData", "해외", "데이터사이언스 · HTML"),
    "aicrowd":      ("AIcrowd", "해외", "AI/ML 챌린지 · HTML"),
    "hkust_cal":    ("HKUST 캘린더", "홍콩", "교내 Competition + 외부 주최 · HTML"),
    "hkust_ec":     ("HKUST 창업센터", "홍콩", "해커톤·창업대회 · HTML"),
    "youthgov":     ("Youth.gov.hk", "홍콩", "홍콩 정부 청년포털 대회 · API"),
    "igem":         ("iGEM", "홍콩", "국제 합성생물학 대회 · API"),
    "hk_devcomm":   ("홍콩 개발자 커뮤니티", "홍콩", "해커톤·개발 행사 · HTML"),
    "hk_seeds":     ("홍콩 주요대회", "홍콩", "연례 대회 '고정 시드' · HTML"),
    "hkstp":        ("HKSTP 이벤트", "홍콩", "홍콩과학기술단지 대회 · HTML"),
    "hkubs":        ("HKU경영대 경진", "홍콩", "HKUBS 학부 경진 · HTML"),
    "luma":         ("Luma 홍콩", "홍콩", "해커톤·대회 이벤트 · API"),
    "eventbrite":   ("Eventbrite 홍콩", "홍콩", "이벤트·해커톤 중 경진 · API"),
    "devpost_hk":   ("Devpost 홍콩", "홍콩", "'hong kong' 검색 해커톤 · API"),
    "kstartup":     ("K-스타트업", "지원사업", "공모전이 아님"),
    "bizinfo":      ("기업마당", "지원사업", "공모전이 아님"),
    "usagov":       ("USA.gov", "지원사업", "미 연방 과제"),
}
assert set(SOURCE_INFO) == set(SOURCE_REGISTRY), "SOURCE_INFO와 SOURCE_REGISTRY의 키가 다릅니다"


def main():
    load_evolved_rules()
    pages = int(os.environ.get("PAGES", "3"))
    max_details = int(os.environ.get("MAX_DETAILS", "60"))
    wanted = [s.strip() for s in
              os.environ.get("SOURCES", DEFAULT_SOURCES).split(",") if s.strip()]

    log.info("=== 1) 수집 시작: %s ===", ", ".join(wanted))
    items = []
    for name in wanted:
        fn = SOURCE_REGISTRY.get(name)
        if not fn:
            log.warning("알 수 없는 소스: %s (건너뜀)", name)
            continue
        try:
            got = fn(pages, max_details)
            items.extend(got)
            log.info("[%s] %d건", name, len(got))
        except Exception as e:
            log.error("[%s] 수집 실패: %s — 다른 소스는 계속 진행", name, e)
    log.info("수집 합계: %d건", len(items))

    log.info("=== 2) 조건 필터링 (재학생·팀·마감 2주+) ===")
    # 홍콩 시간대(GMT+8) 기준으로 필터링 (HONGKONG DUE DATE 정책)
    from scraper.filters import get_hongkong_today
    items = apply_filters(items, today=get_hongkong_today())
    log.info("필터 통과: %d건", len(items))

    llm_cap = int(os.environ.get("LLM_MAX_ITEMS", "40"))
    log.info("=== 3) 학부 분류 + Ollama 정밀 추출 (최대 %d건, 서버 없으면 규칙 기반) ===",
             llm_cap)
    enriched = [enrich(it) for it in items[:llm_cap]]
    # 상한 초과분은 규칙 기반만 적용 (Ollama 호출 생략)
    from scraper.classify import classify_school
    rest = []
    for it in items[llm_cap:]:
        it["학부"] = classify_school(it)
        it.setdefault("team_size", "확인필요")
        it.setdefault("schedule", "확인필요")
        it.setdefault("fee", "확인필요")
        rest.append(it)
    items = enriched + rest
    # LLM이 부적합으로 본 건은 지우지 않고 표시만 한다. 3B 모델은 근거가 없을 때도
    # false를 찍는 일이 있어서, 삭제 권한을 주면 멀쩡한 대회가 조용히 사라진다.
    flagged = sum(1 for it in items if it.get("검토상태") == "LLM판정_부적합")
    if flagged:
        log.info("LLM이 부적합으로 본 %d건 — 삭제하지 않고 '신규후보(LLM의심)'으로 표시", flagged)

    log.info("=== 4) 엑셀 출력 ===")
    os.makedirs(os.path.dirname(OUT_XLSX), exist_ok=True)
    added = write_candidates(items, OUT_XLSX)

    # 검수 웹 DB에도 반영. 엑셀에는 본문이 안 들어가는데, 검수 화면에서 공고를 읽고
    # 판단하려면 본문이 필요하다. 여기서 실패해도 엑셀은 이미 저장돼 있다.
    try:
        from web import db as webdb
        webdb.init()
        new, upd = webdb.upsert_candidates(items)
        log.info("검수 DB 반영: 신규 %d건, 갱신 %d건", new, upd)
    except Exception as e:
        log.warning("검수 DB 반영 실패 (엑셀은 정상 저장됨): %s", e)

    log.info("완료: 최종 후보 %d건, 신규 추가 %d건 → %s", len(items), added, OUT_XLSX)
    # GitHub Actions 커밋 메시지용 출력
    print(f"::notice::신규 후보 {added}건 추가")


if __name__ == "__main__":
    main()
