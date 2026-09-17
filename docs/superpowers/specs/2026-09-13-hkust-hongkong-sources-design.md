# 홍콩 · HKUST 대회 수집 소스 설계 (2026-09-13)

## 목적

학부별 컴피티션 공지에 **홍콩에서 열리는 대회**와 **홍콩과기대(HKUST) 교내 대회**를 포함시킨다.
현재 DB의 홍콩 관련 건은 2건뿐(전부 국내 소스 경유)이라 이 빈틈을 채운다.

## 조사 결과 (2026-09-13 실측)

| 후보 | 결과 |
|---|---|
| `calendar.hkust.edu.hk` | Drupal. "Event Format = Competition" 필터와 "NON-HKUST ORGANIZED EVENTS" 섹션이 있어 교내·외부(홍콩) 대회를 함께 잡을 수 있음. **채택** |
| `ec.hkust.edu.hk/events` | Drupal. 해커톤·창업대회 목록. 상세에 "Deadline :", "Organised by :" 라벨. **채택** |
| `bm.hkust.edu.hk/events` | 경영대 이벤트. 대회 소수. 보류 |
| Cyberport · HKFYG · HKPC | 403 (봇 차단) |
| HKICT Awards · HKGCC | SSL 인증서 오류 |
| HKSTP | 대회 목록이 아니라 프로그램 안내 페이지 |
| Eventbrite | API 키 필요 |
| 캘린더 RSS | Competition 필터를 걸면 거의 비어 있음 |

## 구조

`scraper/hkust.py` 한 파일에 `scrape_calendar()`와 `scrape_ec()` 두 함수. 두 사이트 모두 Drupal이라
본문 컨테이너(`.field--name-body`)·`<time datetime>`·영문 날짜 파싱 헬퍼를 공유한다.
위비티가 `scrape`/`scrape_overseas`를 한 파일에 둔 선례와 같다.

레지스트리 키는 `hkust_cal`, `hkust_ec` 둘. `SOURCE_INFO` 그룹은 새로 `홍콩`,
`DEFAULT_SOURCES`에 포함. 소스 표시명은 `HKUST 캘린더(홍콩)`, `HKUST 창업센터(홍콩)`.
`web/templates/runs.html`의 그룹 목록에 `홍콩`을 추가한다.

### HKUST 캘린더 (`scrape_calendar`)

1. 목록 두 곳: `/events/competition`(교내) + `/events/non-hkust?category=1156`(외부 주최).
   `/events/<slug>` 링크만 모으고 분류 페이지(`/events/competition`, `/events/rss` 등)는 제외.
2. 상세를 1초 간격으로 읽는다(`max_details` 상한). 목록 페이지에 사이드바 강연이 섞여 들어오므로
   상세의 `field--name-field-category`(Event Format)가 `Competition`이 아니면 버린다.
3. 추출: 제목(`h1`), 주최(Organizer), 대상(Recommended For → `target`), 기간(`<time datetime>` 시작/종료,
   UTC → HKT 변환 후 날짜), 본문(`.field--name-body`, 8000자).
4. `location` = `HKUST 교내` 또는 `홍콩(외부 주최)` — 비고에 표시돼 사람이 구분한다.

### HKUST 창업센터 (`scrape_ec`)

1. 목록 `/events?page=0..pages-1`. 카드마다 `h3` 제목, `<time datetime>` 마감, 링크.
2. 상세: 본문(`.field--name-body`), `Organised by :` → host, `Deadline :` → deadline,
   본문의 `Open to …` 문장 → target.
3. 대회가 아닌 강연·멘토십·전시가 섞여 있으므로 제목+본문에
   `hackathon|competition|challenge|contest|pitch|award|prize|cup` 중 하나가 없으면 버린다.

### 마감일

본문에서 `deadline|apply by|application(s)? (close|due)|registration (close|deadline)|submit by` 뒤의
영문 날짜(연도 포함)를 먼저 찾고, 없으면 캘린더는 기간 종료일, 창업센터는 `Deadline :` 값을 쓴다.
기간 종료일은 대회 당일일 수 있으므로 `period` 원문을 함께 남긴다.

### 공통

- `lang = "en"`. 기존 3종 판정·학부 분류·중복 제거는 손대지 않는다.
  Cathay Hackathon처럼 양쪽에 다 있는 건은 정규화 대회명으로 합쳐진다.
- 프록시: 이 서버 셸의 `HTTPS_PROXY=127.0.0.1:7070`을 hkust 도메인이 타면 간헐적으로 끊긴다.
  직접 접속은 안정적이므로 이 모듈은 `requests.Session(trust_env=False)`로 프록시를 우회한다.
- 요청 사이 1초 지연, 브라우저 UA.

## 2차 요청 (같은 날, 사용자 추가 지시)

> "hkust 말고 홍콩에서 열리는 대회 / hkust 각 학부별로 선택 / 지금 크롤링 된 건 다 리셋 / 홍콩이랑 hkust에서만 열리는 걸로"

- **홍콩 전역 소스 추가**: `scraper/youthgov.py`(홍콩 정부 청년포털, Statamic JSON API를 제목 검색어별로 조회 →
  영문·미마감·비(非)스포츠/전시만) + `devpost_hk`(Devpost 'hong kong' 검색, 마감 미경과분; `devpost.scrape`에
  `search`/`source` 인자 추가). 추가 조사에서 HKU·PolyU·StartmeupHK·HKFYG는 대회 비중이 낮거나 JS 렌더링이라 보류.
- **학부별 선택**: 학부 분류는 이미 HKUST 4개 학부(SBM/SENG/SSCI/SHSS)이고 웹 목록의 학부 필터가 그대로 동작한다.
  코드 변경 없음.
- **리셋**: `data/review.sqlite3`·엑셀을 `*.bak_20260913_1142_리셋전`으로 백업한 뒤 candidates/ai_reviews/merges 전부 삭제
  (사람 검수 `reviews`는 0건이라 잃은 것 없음). 엑셀은 삭제 후 재생성.
- **기본 소스**: `DEFAULT_SOURCES = hkust_cal,hkust_ec,youthgov,devpost_hk`. 국내·해외 소스는 레지스트리에 남겨
  웹 체크박스/`SOURCES=`로 켤 수 있다.

## 테스트

- `tests/test_hkust.py`: `tests/fixtures/hkust/`에 저장한 실제 HTML로 파싱 함수 단위 테스트(네트워크 불필요).
  날짜 파싱, 목록 링크 추출, 상세 필드, 대회 여부 판정.
- `tests/test_hkust_live.py`: 네트워크 스모크(기존 `test_wevity_live.py`와 같은 위치).
- `tests/test_youthgov.py`: `tests/fixtures/youthgov/q_*.json`(실제 API 응답) 기반 필터·스키마 테스트.

## 문서

README 소스 표와 DEVELOPMENT §3 파일 지도에 한 줄씩 추가.

## 부수 발견

검수 웹(8000)이 2026-08 말부터 응답 없이 멈춰 있었고, `serve_web.sh` 헬스체크가 실패해도
pid 파일의 프로세스가 살아 있어 gunicorn이 재기동을 거절하는 상태가 1만 회 이상 반복됐다.
2026-09-13 수동 재기동. `serve_web.sh`의 `stop`이 `pkill -f "gunicorn.*web.app:app"`로
같은 골격의 KSAMentoring 웹(8100)까지 죽이는 문제도 확인(KSA 쪽 스크립트는 포트로 한정하고 있음).
