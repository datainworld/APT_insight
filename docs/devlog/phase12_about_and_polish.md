# Phase 12: About 페이지 + 모바일 반응형 + 종료 선언

> 날짜: 2026-04-22
> 커밋: `e00119c`
> 스펙: Phase E (스펙 3.7 + 12장 마감 게이트)

## 목표

- `/about` 스켈레톤 → 8섹션 완성 컨텐츠
- 전 페이지 모바일 반응형 (`< 768px`) 점검
- Dash 대시보드 스펙 전체 구현 종료 선언

D.5 (토큰 스트리밍) 은 사용자 결정으로 생략. E2E 테스트는 infra (`dash[testing]` + selenium) 만 준비된 상태로 종료 — 시나리오 작성은 후속 교재 집필 시.

---

## 1. About 페이지 (스펙 3.7)

### 1.1 구조

단일 컬럼 880px 중앙 정렬, 8섹션 세로 스택.

| # | 섹션 | 내용 |
|---|---|---|
| 1 | 히어로 | 로고 원형 + 제목 + 리드 카피 |
| 2 | 주요 기능 | 6페이지 카드 그리드 (about 자신 제외) |
| 3 | 데이터 소스 | 실시간 커버리지 수치 + 3소스 → DB → agent 흐름 다이어그램 |
| 4 | 핵심 지표 해설 | GLOSSARY 12개 용어 iterate |
| 5 | AI 채팅 사용법 | 4단계 크기 설명 + 예시 질문 + 중단 팁 |
| 6 | PDF RAG | 4단계 가이드 |
| 7 | 기술 스택 | 언어/DB/UI/agents/LLM/파싱/배포 |
| 8 | 버전 · 문의 | v0.1.0 + 교재 원료 표기 |

### 1.2 핵심 지표 해설 — GLOSSARY iterate

스펙 3.7 "4번 섹션이 `glossary/terms.py` 와 같은 소스를 사용하므로 용어 정의 수정이 자동 반영됨" 의도대로:

```python
def _section_glossary():
    rows = []
    for _, term in GLOSSARY.items():  # 12개 전체
        children = [
            html.B(term["label"]),
            html.P(term["long"] or term["short"], className="term-long"),
        ]
        if term.get("formula"):
            children.append(html.Code(term["formula"], className="term-formula"))
        if term.get("example"):
            children.append(html.Div([...], className="term-example"))
        rows.append(html.Div(className="term-item", children=children))
    return html.Section(children=[html.H2("핵심 지표 해설"), html.Div(rows)])
```

용어 12개 모두 `label / long / formula / example` 정보로 정의됨. About 페이지는 이 사전을 직접 참조 — 용어 수정 시 About 자동 반영.

### 1.3 데이터 소스 — 실시간 커버리지

신규 모듈 `queries/coverage_queries.py`:

```python
@lru_cache(maxsize=1)  # 프로세스 수명 동안 1회만 조회 (About 페이지 호출 빈도 낮음)
def get_coverage() -> dict:
    sql = text("""
        SELECT
            (SELECT COUNT(*) FROM rt_complex)                           AS rt_complex,
            (SELECT COUNT(*) FROM rt_trade)                             AS rt_trade,
            (SELECT COUNT(*) FROM rt_rent)                              AS rt_rent,
            (SELECT COUNT(*) FROM nv_complex)                           AS nv_complex,
            (SELECT COUNT(*) FROM nv_listing WHERE is_active = TRUE)    AS nv_active,
            (SELECT COUNT(*) FROM complex_mapping)                      AS mapping,
            (SELECT COUNT(*) FROM news_articles)                        AS news
    """)
    ...

def get_pdf_count() -> int:
    """PGVector 에 적재된 문서 파일 수 (고유 source 기준)."""
    try:
        sql = text(
            "SELECT COUNT(DISTINCT cmetadata->>'source') FROM langchain_pg_embedding"
        )
        with get_engine().connect() as conn:
            return int(conn.execute(sql).scalar() or 0)
    except Exception:
        return 0
```

`lru_cache` — 프로세스 수명 1회 실행으로 충분. About 페이지는 세션당 1~2번 조회 정도이므로 실시간성 > 메모리 비용.

`get_pdf_count()` 는 `langchain_pg_embedding` 테이블 존재 여부가 불확실 (PGVector 가 지연 생성). `try/except` 로 감싸 0 반환.

다이어그램은 HTML/CSS 기반 (SVG 대신):

```python
html.Div(className="about-flow", children=[
    html.Div(className="flow-box flow-src", children=[_fa("database"), html.B("국토부 실거래가"), ...]),
    html.Div(className="flow-box flow-src", children=[_fa("globe"), html.B("네이버 부동산"), ...]),
    html.Div(className="flow-box flow-src", children=[_fa("newspaper"), html.B("네이버 뉴스"), ...]),
    html.Div(_fa("arrow-right-long"), className="flow-arrow"),
    html.Div(className="flow-box flow-db",    children=[_fa("server"), html.B("APT Insight DB"), ...]),
    html.Div(_fa("arrow-right-long"), className="flow-arrow"),
    html.Div(className="flow-box flow-agent", children=[_fa("robot"), html.B("SQL · RAG · News 에이전트"), ...]),
])
```

flex + 색상으로 소스 (accent-2) / DB (accent-1) / agent (orange) 구분.

### 1.4 AI 채팅 사용법

4단계 크기 설명을 `<code>` + `<b>` + 설명으로 카드 grid 형태:

```python
sizes = [
    ("minimized", "최소화", "아이콘 56×56, 우하단 고정"),
    ("compact", "컴팩트", "400×640, 기본 열림 상태"),
    ("expanded", "확장", "우측 도크 · 전체 높이"),
    ("maximized", "최대화", "전체 화면 — 긴 차트·테이블 용"),
]
```

예시 질문은 `CHIP_PROMPTS` 3개 + 추가 3개:
- 강남구 최근 거래 추이 (CHIP)
- 호가 괴리가 큰 단지 (CHIP)
- 갭투자 유망 단지 추천 (CHIP)
- 노원구에서 최근 전세 거래된 아파트 상위 10개
- 서울에서 평당가가 가장 높은 자치구 TOP 5
- 분당구 재건축 관련 최근 뉴스 요약

중단 팁도 인포 박스로.

### 1.5 CTA 버튼 제거 (사용자 피드백)

초기 히어로에는 `"시장 개요 보러가기"` `"지역 심층"` 두 버튼. 사용자: **"버튼 영역 삭제하고 다음 진행하자"**. 대시보드 내부 페이지라 상단 네비로 이미 접근 가능, 중복 CTA 제거.

---

## 2. 모바일 반응형 (`< 768px`)

### 2.1 초기 시도 — 실패

간단한 grid → 1컬럼 변환만으로 충분할 줄 알았음:

```css
@media (max-width: 768px) {
    .fd-shell { grid-template-columns: 1fr; grid-template-rows: auto 1fr; height: 100vh; }
    .filter-side { max-height: 40vh; border-bottom: 1px solid var(--border-1); }
    .row2-28 { grid-template-columns: 1fr; }
    .kpi-strip { grid-template-columns: repeat(2, 1fr); }
    ...
}
```

### 2.2 사용자 제보 1

> 메뉴, 조건필터링 확인 불가. 36개월 거래량 실종 등.

사이드바가 40vh 를 잡아먹어 필터 컨트롤이 꽉 차고, 본문 1fr 은 비좁아 콘텐츠 일부 안 보임.

**수정**: 필터 섹션을 **모바일에선 숨기고 nav 만 compact 한 가로 스트립**:

```css
.filter-side > .filter-body,
.filter-side .filter-group,
.filter-side .stamp {
    display: none !important;
}
.page-nav {
    display: flex; flex-direction: row;
    overflow-x: auto; gap: 4px;
}
```

판단: 모바일은 주로 **보기 용도**. 필터링이 필요하면 데스크톱에서. 필터를 유지하려면 burger menu 토글 필요한데 Phase E 범위 밖.

### 2.3 사용자 제보 2 — 결정적 이슈

> 모바일뷰에서 세로 스크롤 불가함.

재현: 뷰포트 너비를 768px 이하로 줄이면 KPI → 맵 → (트렌드 차트는 아래에 있어야 하는데) 스크롤이 안 됨.

**원인 분석**:
```css
html, body { height: 100%; overflow: hidden; }       /* 데스크톱 용 */
.fd-shell { height: 100vh; display: grid; }          /* 세로 2행 */
#_pages_content { height: 100%; overflow-y: auto; }  /* 내부 스크롤 */
.fd-main { overflow-y: auto; }                       /* 이중 중첩 */
```

데스크톱은 `#_pages_content` 가 스크롤 주체라 작동. 모바일에서:
- `html, body { overflow: hidden }` 이 모바일 터치 스크롤과 충돌
- `100vh` 기반 grid 는 iOS Safari 에서 부정확 (주소창 크기 변동)
- 중첩 스크롤 컨테이너는 모바일 터치 이벤트 처리에서 자주 깨짐

### 2.4 결정적 해결 — body 스크롤 전환

모바일에선 데스크톱의 중첩 구조를 버리고 **정상적인 document scroll** 사용:

```css
@media (max-width: 768px) {
    html, body { height: auto; overflow: auto; }        /* 페이지 전체 스크롤 */
    .fd-shell {
        display: block; height: auto; min-height: 100vh;
        grid-template-columns: none; grid-template-rows: none;
    }
    #_pages_content { height: auto; overflow: visible; }
    .fd-main { overflow: visible; }
    .filter-side {
        position: sticky; top: 0; z-index: 50;          /* 네비 상단 고정 */
        padding: 8px 10px;
        gap: 0;
        border-right: none; border-bottom: 1px solid var(--border-1);
        overflow: visible;
    }
    ...
}
```

핵심 변화:
- `html, body` overflow 해제 → 기본 document 스크롤 동작
- `.fd-shell` grid 해제 → block 배치로 자연스러운 세로 흐름
- 모든 overflow: auto 해제 → 중첩 스크롤 없음
- 사이드바만 `position: sticky` 로 상단 고정 (스크롤 해도 네비 접근 가능)

데스크톱은 기존 grid + nested scroll 유지. 미디어 쿼리로 완전 분리.

### 2.5 추가 반응형 규칙

| 영역 | 모바일 전환 |
|---|---|
| `.row2-28` / `.row3-insight` | 1컬럼 |
| `.kpi-strip` | 4열 → 2열 |
| `.chat-panel[data-size="compact|expanded"]` | 화면 거의 전체 |
| `.uploads-drawer` | 300px → 화면 거의 전체 |
| `.page-nav .brand` | 숨김 (공간 절약) |
| `.page-nav a` | font 11px · padding 축소 |
| `.about-grid` / `.about-sizes` | 1컬럼 |
| `.about-stats` | 4열 → 2열 |
| `.about-flow` | 가로 flex → 세로 flex + 화살표 회전 |

---

## 3. 교재 포인트 요약

1. **GLOSSARY 를 About 페이지에서 iterate** — 단일 진실 공급원 (`glossary/terms.py`) 이 맵 KPI 툴팁 + About 상세 설명을 함께 공급. 용어 추가/수정 시 한 곳만 고치면 됨.
2. **`lru_cache(maxsize=1)`** — About 페이지처럼 호출 빈도 낮은 범용 조회에 프로세스 수명 캐시가 간단하고 효과적. 실시간성보다 안정성 우선.
3. **모바일 반응형 = 구조 전환**. media query 로 `grid-template` 을 바꾸는 것만으론 부족. `html, body` overflow 와 viewport unit (`100vh`) 은 모바일 브라우저에서 이상 동작 — document scroll 으로 근본 구조를 바꿔야 안전.
4. **position: sticky** 로 모바일 top nav — `position: fixed` 보다 자연스럽고 레이아웃 흐름 유지.
5. **dmc 대신 html.Div + CSS transform drawer** — MantineProvider 의존성 회피. 250ms transition 만으로 충분한 UX.

---

## 4. 최종 상태

### 4.1 커밋 이력 (Phase 9~12)

| 커밋 | Phase | 주요 내용 |
|---|---|---|
| `e312096` | A+B | 멀티페이지 스캐폴딩 (7 페이지) |
| `a6e888e` | C.0 | DDL + 쿼리 + 공통 컴포넌트 |
| `456effc` | C.1 | region/gap/invest 페이지 |
| `7436b1b` | fix | nav 라우팅 (dcc.Link → html.A) + PG date |
| `7671ebd` | fix | GeoJSON 교체 + 이름 정규화 + hideout 패턴 |
| `8128bde` | C.2 | complex/insight + 평당가 정합성 |
| `1e28d5a` | C.3 | 홈 업그레이드 + 필터 단순화 |
| `27bd90d` | D.1/D.3 | 4단계 채팅 + markdown/table 렌더 + 중단 |
| `e7018c7` | D.4 | PDF 업로드 + ingest_pdf |
| `e00119c` | **E** | About + 모바일 반응형 |

### 4.2 최종 기능 범위

- **7 페이지** 전부 실데이터 동작
- **채팅 4단계** + ESC + 중단 + markdown/table/plotly 렌더
- **PDF RAG** — 업로드 → PyMuPDF 파싱 → 청킹 → PGVector 적재
- **평당가 정합성** — 모든 가격 비교를 면적 정규화
- **GeoJSON** kostat 2013 + 시군구명 정규화 (Incheon 남구→미추홀구, 경기 공백)
- **반응형** 데스크톱(grid) + 모바일(document scroll) 완전 분기
- **테스트** 47개 단위 (ruff + mypy + pytest all green)

### 4.3 남은 과제 (스펙 12장 게이트 대비)

- **D.5 토큰 스트리밍** — 중단 기능으로 대체 (사용자 결정)
- **E2E 테스트** — 인프라 준비, 시나리오는 후속
- **Lighthouse 80+** — 수동 실행 가능, 공식 기록 미수행
- **다크모드 토글** — 다크 기본 테마 외 라이트 모드 미구현 (스펙상 "신규 CSS 는 `[data-theme="dark"]` 변형 정의" 만 요구 — 실제 라이트 모드 지원은 범위 외로 판단)

---

## 5. 전체 Phase 진행 총괄 (교재 목차 제안)

교재 advance 과정의 챕터 구성 제안:

1. **Phase 0~5** — 초기 프로젝트 셋업 (이미 기록됨)
2. **Phase 6~8** — 에이전트 리팩토링 + 성능 최적화 (이미 기록됨)
3. **Phase 9** (현재 scaffold) — **"기존 시스템 확장의 리팩토링 기법"**
   - 물리 이동 우선 원칙
   - 운영 제약 vs 스펙의 타협
   - 의존성 일괄 추가
4. **Phase 10** (pages) — **"도메인 원칙을 코드에 녹이기"**
   - 평당가 정합성 전파
   - 데이터 품질 검증 (GeoJSON GeometryCollection)
   - 시군구명 정규화
   - 라이브러리 함정 (dcc.Link pattern-matching ID)
5. **Phase 11** (chat) — **"LLM 에이전트 UI 통합"**
   - 4단계 크기 전환 패턴
   - 컨텍스트 주입의 양날
   - Background callback + 중단
   - agents 수정 없이 RAG 파이프라인 확장
6. **Phase 12** (about + polish) — **"마감 작업과 반응형"**
   - GLOSSARY 단일 진실 공급원
   - 모바일 반응형의 구조적 전환
   - 무한 대기 해결 (JS 캐시)

각 챕터는 **의사결정 왜 (Why)** 가 **구현 방법 (How)** 보다 먼저. 교재 독자에게 실전 맥락을 전달하기 위함.
