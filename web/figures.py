# -*- coding: utf-8 -*-
"""학습 사이트에 들어가는 그림 (인라인 SVG).

외부 이미지 파일이나 도표 라이브러리를 쓰지 않는다. SVG를 HTML에 그대로 심으면
인터넷이 없어도, 파일을 통째로 옮겨도 안 깨진다.
"""

ARROW = ('<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
         'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#8fa0b3"/>'
         '</marker></defs>')


# ---------------------------------------------------------------- 1일차
REQUEST = f'''<svg viewBox="0 0 660 210" role="img" aria-label="브라우저와 파이썬이 같은 서버에서 같은 글자를 받는 그림">
{ARROW}
<text x="70" y="26" class="s-ink" font-size="13" font-weight="600" text-anchor="middle">사람 (브라우저)</text>
<rect x="14" y="38" width="112" height="62" rx="6" class="s-box"/>
<text x="70" y="63" class="s-ink" font-size="11" text-anchor="middle">공모전 페이지가</text>
<text x="70" y="79" class="s-ink" font-size="11" text-anchor="middle">예쁘게 보임</text>

<text x="70" y="140" class="s-ink" font-size="13" font-weight="600" text-anchor="middle">우리 (파이썬)</text>
<rect x="14" y="152" width="112" height="44" rx="6" class="s-box"/>
<text x="70" y="179" font-size="10.5" text-anchor="middle" fill="#6b7684">requests.get(...)</text>

<path d="M132,68 L246,68" class="s-arrow" marker-end="url(#a)"/>
<path d="M132,174 L246,174" class="s-arrow" marker-end="url(#a)"/>
<text x="189" y="60" class="s-mut" font-size="10" text-anchor="middle">"이 주소 주세요"</text>
<text x="189" y="166" class="s-mut" font-size="10" text-anchor="middle">"이 주소 주세요"</text>

<rect x="252" y="52" width="96" height="138" rx="6" fill="#1f4e79"/>
<text x="300" y="112" fill="#fff" font-size="13" font-weight="600" text-anchor="middle">서버</text>
<text x="300" y="132" fill="#a9c3dc" font-size="10" text-anchor="middle">wevity.com</text>

<path d="M354,121 L474,121" class="s-arrow" marker-end="url(#a)"/>
<text x="414" y="112" class="s-ok" font-size="11" font-weight="600" text-anchor="middle">200</text>
<text x="414" y="140" class="s-mut" font-size="10" text-anchor="middle">둘 다 똑같은 것을 받는다</text>

<rect x="480" y="52" width="166" height="138" rx="6" fill="#10161d"/>
<text x="496" y="76" fill="#cfe0ee" font-size="10.5" font-family="monospace">&lt;!DOCTYPE html&gt;</text>
<text x="496" y="94" fill="#cfe0ee" font-size="10.5" font-family="monospace">&lt;div class="cd-area"&gt;</text>
<text x="496" y="112" fill="#cfe0ee" font-size="10.5" font-family="monospace">  &lt;li&gt;응모대상</text>
<text x="496" y="130" fill="#cfe0ee" font-size="10.5" font-family="monospace">      제한없음&lt;/li&gt;</text>
<text x="496" y="148" fill="#cfe0ee" font-size="10.5" font-family="monospace">&lt;/div&gt;</text>
<text x="563" y="176" fill="#8fa0b3" font-size="10" text-anchor="middle">HTML — 그냥 글자다</text>
</svg>'''


# ---------------------------------------------------------------- 3일차
CRAWL = f'''<svg viewBox="0 0 660 200" role="img" aria-label="목록에서 주소를 모아 상세를 하나씩 방문하는 흐름">
{ARROW}
<rect x="14" y="42" width="132" height="112" rx="6" class="s-box"/>
<text x="80" y="30" class="s-ink" font-size="12" font-weight="600" text-anchor="middle">① 목록 페이지</text>
<text x="30" y="68" class="s-mut" font-size="10.5">· 대회 A → ix=107427</text>
<text x="30" y="88" class="s-mut" font-size="10.5">· 대회 B → ix=107425</text>
<text x="30" y="108" class="s-mut" font-size="10.5">· 대회 C → ix=108417</text>
<text x="30" y="134" class="s-acc" font-size="10.5">주소만 모은다</text>

<path d="M152,98 L214,98" class="s-arrow" marker-end="url(#a)"/>

<rect x="220" y="42" width="128" height="112" rx="6" class="s-box"/>
<text x="284" y="30" class="s-ink" font-size="12" font-weight="600" text-anchor="middle">② 하나씩 방문</text>
<text x="236" y="70" class="s-mut" font-size="10.5">?ix=107427 →</text>
<text x="236" y="90" class="s-mut" font-size="10.5">?ix=107425 →</text>
<text x="236" y="110" class="s-mut" font-size="10.5">?ix=108417 →</text>
<text x="236" y="136" class="s-warn" font-size="10.5">1초씩 쉬면서</text>

<path d="M354,98 L416,98" class="s-arrow" marker-end="url(#a)"/>

<rect x="422" y="42" width="224" height="112" rx="6" class="s-box"/>
<text x="534" y="30" class="s-ink" font-size="12" font-weight="600" text-anchor="middle">③ 값 뽑기</text>
<text x="438" y="70" class="s-ink" font-size="10.5">제목  : 2026 ACC 영상 공모전</text>
<text x="438" y="90" class="s-ink" font-size="10.5">마감  : 2026-07-31</text>
<text x="438" y="110" class="s-ink" font-size="10.5">응모대상: 제한없음</text>
<text x="438" y="136" class="s-acc" font-size="10.5">공통 모양으로 맞춰 넘긴다</text>

<text x="217" y="180" class="s-mut" font-size="11" text-anchor="middle">← 크롤링 (돌아다니며 모으기) →</text>
<text x="534" y="180" class="s-mut" font-size="11" text-anchor="middle">← 스크래핑 (값 뽑기) →</text>
</svg>'''


# ---------------------------------------------------------------- 4일차 (핵심)
LEAK = f'''<svg viewBox="0 0 660 330" role="img" aria-label="페이지 전체를 퍼오면 메뉴의 대학생이라는 단어가 섞여 들어오는 그림">
{ARROW}
<text x="150" y="22" class="s-ink" font-size="12.5" font-weight="600" text-anchor="middle">위비티 공고 페이지 한 장</text>

<rect x="14" y="34" width="272" height="228" rx="6" fill="#fbfcfd" stroke="#cbd5e0"/>
<rect x="22" y="42" width="256" height="26" rx="4" fill="#eef2f6"/>
<text x="150" y="59" class="s-mut" font-size="10.5" text-anchor="middle">상단 검색창 · 로고</text>

<rect x="22" y="76" width="86" height="150" rx="4" fill="#fdf0f1" stroke="#f0c4c6"/>
<text x="65" y="94" class="s-no" font-size="10" font-weight="600" text-anchor="middle">좌측 메뉴</text>
<text x="30" y="114" class="s-no" font-size="9.5">공모전전략</text>
<text x="30" y="132" class="s-mut" font-size="9.5">대외활동</text>
<text x="30" y="152" class="s-mut" font-size="9.5">응시대상자</text>
<text x="30" y="170" class="s-mut" font-size="9.5"> 제한없음</text>
<text x="30" y="188" class="s-no" font-size="9.5"> 대학생</text>
<text x="30" y="206" class="s-no" font-size="9.5"> 청소년</text>

<rect x="116" y="76" width="162" height="150" rx="4" fill="#f2faf5" stroke="#bfe0cc"/>
<text x="197" y="94" class="s-ok" font-size="10" font-weight="600" text-anchor="middle">div.comm-desc</text>
<text x="126" y="114" class="s-ink" font-size="9.5">■ 공모주제: AI 시대…</text>
<text x="126" y="132" class="s-ink" font-size="9.5">■ 공모자격: 개인</text>
<text x="126" y="150" class="s-ink" font-size="9.5">■ 접수방법: 유튜브…</text>
<text x="126" y="168" class="s-ink" font-size="9.5">■ 시상내역: 대상 1명</text>
<text x="197" y="200" class="s-ok" font-size="9.5" text-anchor="middle">진짜 공고는 여기뿐</text>

<rect x="22" y="234" width="256" height="20" rx="4" fill="#eef2f6"/>
<text x="150" y="248" class="s-mut" font-size="10" text-anchor="middle">푸터 · 회사 정보</text>

<path d="M292,110 L346,110" class="s-arrow" marker-end="url(#a)"/>
<path d="M292,196 L346,196" class="s-arrow" marker-end="url(#a)"/>

<rect x="352" y="72" width="294" height="80" rx="6" fill="#fdf5f5" stroke="#f0c4c6"/>
<text x="366" y="92" class="s-no" font-size="11" font-weight="600">✗ soup.get_text()  — 페이지 전체</text>
<text x="366" y="114" class="s-ink" font-size="10.5">'대학생' 1번 · '청소년' 1번 · '전략' 2번</text>
<text x="366" y="136" class="s-no" font-size="10.5">→ 자격을 안 밝힌 공고도 "대학생 가능"</text>

<rect x="352" y="164" width="294" height="80" rx="6" fill="#f2faf5" stroke="#bfe0cc"/>
<text x="366" y="184" class="s-ok" font-size="11" font-weight="600">✓ find('div', class_='comm-desc')</text>
<text x="366" y="206" class="s-ink" font-size="10.5">'대학생' 0번 · '청소년' 0번 · '전략' 0번</text>
<text x="366" y="228" class="s-ok" font-size="10.5">→ 근거 없으면 '확인필요'로 남는다</text>

<text x="330" y="296" class="s-warn" font-size="11.5" font-weight="600" text-anchor="middle">이 공고 본문에는 '대학생'이 한 번도 안 나옵니다.</text>
<text x="330" y="316" class="s-mut" font-size="11" text-anchor="middle">전체를 퍼오면 왼쪽 메뉴가 그 말을 대신 해줍니다.</text>
</svg>'''


# ---------------------------------------------------------------- 5일차
API_VS_HTML = f'''<svg viewBox="0 0 660 240" role="img" aria-label="HTML을 뜯는 방식과 API를 쓰는 방식 비교">
<rect x="14" y="30" width="306" height="196" rx="6" class="s-box"/>
<text x="167" y="52" class="s-ink" font-size="12.5" font-weight="600" text-anchor="middle">HTML 뜯기</text>
<rect x="28" y="64" width="278" height="74" rx="4" fill="#10161d"/>
<text x="40" y="84" fill="#cfe0ee" font-size="10" font-family="monospace">&lt;div class="cd-area"&gt;</text>
<text x="40" y="100" fill="#cfe0ee" font-size="10" font-family="monospace">  &lt;li&gt;&lt;span&gt;응모대상&lt;/span&gt;</text>
<text x="40" y="116" fill="#cfe0ee" font-size="10" font-family="monospace">     제한없음&lt;/li&gt;</text>
<text x="40" y="132" fill="#cfe0ee" font-size="10" font-family="monospace">&lt;/div&gt;</text>
<text x="30" y="160" class="s-mut" font-size="10.5">· 꺾쇠를 헤치고 값을 찾아야 함</text>
<text x="30" y="180" class="s-no" font-size="10.5">· 디자인 바뀌면 깨짐</text>
<text x="30" y="200" class="s-mut" font-size="10.5">· 메뉴가 섞일 위험 (4일차)</text>

<rect x="340" y="30" width="306" height="196" rx="6" fill="#f2faf5" stroke="#bfe0cc"/>
<text x="493" y="52" class="s-ok" font-size="12.5" font-weight="600" text-anchor="middle">API 쓰기</text>
<rect x="354" y="64" width="278" height="74" rx="4" fill="#10161d"/>
<text x="366" y="84" fill="#9fe3bd" font-size="10" font-family="monospace">{{</text>
<text x="366" y="100" fill="#9fe3bd" font-size="10" font-family="monospace">  "name": "풍력발전량 예측…",</text>
<text x="366" y="116" fill="#9fe3bd" font-size="10" font-family="monospace">  "period_end": "2026-08-14"</text>
<text x="366" y="132" fill="#9fe3bd" font-size="10" font-family="monospace">}}</text>
<text x="356" y="160" class="s-ok" font-size="10.5">· c['name'] 으로 바로 꺼냄</text>
<text x="356" y="180" class="s-ok" font-size="10.5">· 디자인 바뀌어도 안 깨짐</text>
<text x="356" y="200" class="s-mut" font-size="10.5">· 사이트가 열어줘야 가능</text>
</svg>'''


# ---------------------------------------------------------------- 6일차
POLITE = f'''<svg viewBox="0 0 660 190" role="img" aria-label="새 사이트를 붙이기 전 확인 순서">
{ARROW}
<rect x="14" y="60" width="128" height="58" rx="6" class="s-box"/>
<text x="78" y="84" class="s-ink" font-size="11.5" font-weight="600" text-anchor="middle">robots.txt</text>
<text x="78" y="102" class="s-mut" font-size="10" text-anchor="middle">긁어도 되나?</text>

<path d="M148,89 L206,89" class="s-arrow" marker-end="url(#a)"/>
<text x="177" y="80" class="s-ok" font-size="10" text-anchor="middle">허용</text>

<rect x="212" y="60" width="128" height="58" rx="6" class="s-box"/>
<text x="276" y="84" class="s-ink" font-size="11.5" font-weight="600" text-anchor="middle">API 찾기</text>
<text x="276" y="102" class="s-mut" font-size="10" text-anchor="middle">F12 → Network</text>

<path d="M346,89 L404,89" class="s-arrow" marker-end="url(#a)"/>

<rect x="410" y="60" width="128" height="58" rx="6" class="s-box"/>
<text x="474" y="84" class="s-ink" font-size="11.5" font-weight="600" text-anchor="middle">본문 요소</text>
<text x="474" y="102" class="s-mut" font-size="10" text-anchor="middle">메뉴 빼고</text>

<path d="M544,89 L594,89" class="s-arrow" marker-end="url(#a)"/>
<text x="620" y="86" class="s-ok" font-size="11.5" font-weight="600" text-anchor="middle">수집</text>
<text x="620" y="104" class="s-mut" font-size="10" text-anchor="middle">1초씩 쉬며</text>

<path d="M78,124 L78,152" class="s-arrow" marker-end="url(#a)"/>
<text x="100" y="142" class="s-no" font-size="10">금지</text>
<rect x="14" y="152" width="128" height="28" rx="6" fill="#fdf0f1" stroke="#f0c4c6"/>
<text x="78" y="171" class="s-no" font-size="11" font-weight="600" text-anchor="middle">여기서 끝. 안 한다</text>

<text x="340" y="34" class="s-mut" font-size="11" text-anchor="middle">막혀 있으면 뚫는 게 아니라, 다른 길을 찾습니다.</text>
</svg>'''


# ---------------------------------------------------------------- 8일차
THREE = f'''<svg viewBox="0 0 660 250" role="img" aria-label="통과 탈락 확인필요 세 값으로 판정하는 흐름">
{ARROW}
<rect x="240" y="20" width="180" height="40" rx="6" class="s-box"/>
<text x="330" y="45" class="s-ink" font-size="12" font-weight="600" text-anchor="middle">공고 본문을 읽는다</text>

<path d="M330,64 L330,92" class="s-arrow" marker-end="url(#a)"/>
<rect x="228" y="92" width="204" height="42" rx="6" fill="#fdf5f5" stroke="#f0c4c6"/>
<text x="330" y="110" class="s-no" font-size="11.5" font-weight="600" text-anchor="middle">"안 된다"는 근거가 있나?</text>
<text x="330" y="127" class="s-mut" font-size="10" text-anchor="middle">초·중·고 전용 / 개인 참가만 / 팀 불가</text>

<path d="M228,113 L136,113 L136,176" class="s-arrow" marker-end="url(#a)"/>
<text x="176" y="106" class="s-no" font-size="10" text-anchor="middle">있다</text>
<rect x="72" y="176" width="128" height="46" rx="6" fill="#fdf0f1" stroke="#f0c4c6"/>
<text x="136" y="197" class="s-no" font-size="13" font-weight="600" text-anchor="middle">탈락</text>
<text x="136" y="214" class="s-mut" font-size="10" text-anchor="middle">목록에서 뺀다</text>

<path d="M330,138 L330,160" class="s-arrow" marker-end="url(#a)"/>
<text x="352" y="153" class="s-mut" font-size="10">없다</text>
<rect x="228" y="160" width="204" height="34" rx="6" fill="#f2faf5" stroke="#bfe0cc"/>
<text x="330" y="182" class="s-ok" font-size="11.5" font-weight="600" text-anchor="middle">"된다"는 근거가 있나?</text>

<path d="M432,177 L524,177 L524,140" class="s-arrow" marker-end="url(#a)"/>
<text x="486" y="170" class="s-ok" font-size="10" text-anchor="middle">있다</text>
<rect x="460" y="94" width="128" height="46" rx="6" fill="#f2faf5" stroke="#bfe0cc"/>
<text x="524" y="115" class="s-ok" font-size="13" font-weight="600" text-anchor="middle">통과</text>
<text x="524" y="132" class="s-mut" font-size="10" text-anchor="middle">자동으로 확인됨</text>

<path d="M330,198 L330,214" class="s-arrow" marker-end="url(#a)"/>
<rect x="256" y="214" width="148" height="30" rx="6" fill="#fffbef" stroke="#e8d9a8"/>
<text x="330" y="234" class="s-warn" font-size="12.5" font-weight="600" text-anchor="middle">확인필요 — 사람이 본다</text>

<text x="596" y="222" class="s-mut" font-size="11" text-anchor="end">모른다 ≠ 아니다</text>
<text x="596" y="240" class="s-mut" font-size="11" text-anchor="end">놓치느니 남긴다</text>
</svg>'''


# ---------------------------------------------------------------- 10일차
PIPELINE = f'''<svg viewBox="0 0 660 250" role="img" aria-label="수집부터 검수까지 전체 흐름">
{ARROW}
<rect x="14" y="26" width="150" height="66" rx="6" class="s-box"/>
<text x="89" y="48" class="s-ink" font-size="12" font-weight="600" text-anchor="middle">① 수집</text>
<text x="89" y="67" class="s-mut" font-size="10" text-anchor="middle">사이트 16곳</text>
<text x="89" y="83" class="s-mut" font-size="10" text-anchor="middle">주 1회 · 약 26분</text>

<path d="M170,59 L214,59" class="s-arrow" marker-end="url(#a)"/>

<rect x="220" y="26" width="150" height="66" rx="6" class="s-box"/>
<text x="295" y="48" class="s-ink" font-size="12" font-weight="600" text-anchor="middle">② 판정</text>
<text x="295" y="67" class="s-mut" font-size="10" text-anchor="middle">재학생 · 팀 · 마감</text>
<text x="295" y="83" class="s-warn" font-size="10" text-anchor="middle">애매하면 확인필요</text>

<path d="M376,59 L420,59" class="s-arrow" marker-end="url(#a)"/>

<rect x="426" y="26" width="150" height="66" rx="6" class="s-box"/>
<text x="501" y="48" class="s-ink" font-size="12" font-weight="600" text-anchor="middle">③ 보강</text>
<text x="501" y="67" class="s-mut" font-size="10" text-anchor="middle">로컬 AI가 빈칸 채움</text>
<text x="501" y="83" class="s-mut" font-size="10" text-anchor="middle">팀 인원 · 일정 · 참가비</text>

<path d="M295,98 L295,126" class="s-arrow" marker-end="url(#a)"/>
<path d="M501,98 L501,118 L305,118" class="s-arrow"/>

<rect x="180" y="126" width="300" height="54" rx="6" fill="#eef4fa" stroke="#9dc0dd"/>
<text x="330" y="148" class="s-acc" font-size="12.5" font-weight="600" text-anchor="middle">④ 검수 웹 — 사람이 확정·기각</text>
<text x="330" y="168" class="s-mut" font-size="10.5" text-anchor="middle">지금 후보 260여 건</text>

<path d="M180,153 L110,153 L110,204" class="s-arrow" marker-end="url(#a)"/>
<rect x="30" y="204" width="160" height="38" rx="6" class="s-box"/>
<text x="110" y="228" class="s-ink" font-size="11.5" text-anchor="middle">공지용 엑셀</text>

<path d="M480,153 L550,153 L550,204" class="s-arrow" marker-end="url(#a)"/>
<rect x="470" y="204" width="176" height="38" rx="6" fill="#f2faf5" stroke="#bfe0cc"/>
<text x="558" y="220" class="s-ok" font-size="11" font-weight="600" text-anchor="middle">판정 규칙 학습</text>
<text x="558" y="236" class="s-mut" font-size="9.5" text-anchor="middle">확정=맞는 예 · 기각=틀린 예</text>

<text x="330" y="196" class="s-mut" font-size="10.5" text-anchor="middle">사람이 누른 판단이 규칙을 가르칩니다</text>
</svg>'''
