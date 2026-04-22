# Phase 9: Dash 대시보드 멀티페이지 스캐폴딩

> 날짜: 2026-04-20 ~ 2026-04-21
> 커밋: `e312096`, `a6e888e`
> 스펙: `docs/DASH_ENHANCEMENT_SPEC.md` Phase A+B + C.0

## 목표

기존 단일 페이지(`dash_app/`) 를 **7페이지 구조**로 확장한다. Chainlit 과 무관하게 Dash 단독으로 확장하며, 이번 Phase 는:

- 디렉토리 재구조화 (pages / components / queries / callbacks / glossary)
- 7페이지 `dash.register_page` 등록 (홈 + 6 스켈레톤)
- Phase A+B 게이트: `ruff`/`mypy`/`pytest` 전원 green + 기존 홈 페이지 회귀 없음
- Phase C.0 인프라: DDL (news_articles + 2 MV) + 쿼리 모듈 뼈대 + 공통 컴포넌트 5종

---

## 1. 초기 판단 (사용자 의사결정 5건)

| 질문 | 결정 | 이유 |
|---|---|---|
| Phase 진행 단위 | A+B 병합 | 페이지 구조 + 멀티페이지 뼈대는 함께 해야 의미 있음 |
| 의존성 추가 시점 | Phase A 시작 시 한 번에 | `dash-leaflet / ag-grid / mantine / cachetools` 등 점진 추가하면 중간에 실패 케이스 많음 |
| Chainlit 공존 | 유지 (루트 `app.py` 건드리지 않음) | 교재용 비교 자료로 Chainlit 버전도 참고 가능 |
| 테스트 인프라 | Phase A 에서 세팅 | `dash[testing]` + `testcontainers` 를 조기에 넣어 이후 회귀 방지 |
| 커밋 단위 | Phase 단위 PR | 리뷰 흐름과 교재 챕터 단위에 맞춤 |

### 네비 위치 (판단 1개)
원본 디자인 `filtered_dashboard.html` 은 단일 페이지 기준이라 7페이지 네비게이션 자리가 없었다. 3가지 옵션 중 **(A) 기존 좌측 사이드바 상단에 네비 추가** 를 선택 — 필터 구조는 그대로 유지, 네비가 추가되는 최소 침습 형태.

---

## 2. 디렉토리 재구조화

### Before (Phase A+B 시작 전)
```
dash_app/
├── app.py              # 단일 Dash 엔트리 (67줄)
├── components.py       # 사이드바·KPI·탭·테이블·챗 (490줄, 혼재)
├── callbacks.py        # cascade·차트·지도·챗 invoke (651줄, 혼재)
├── charts.py           # Plotly Figure 팩토리
├── db.py               # 엔진 + 집계 쿼리 (303줄, 혼재)
├── theme.py            # 색·폰트·다크 토큰
└── assets/             # CSS, JS
```

총 ~1,772줄 / 7 파일. 페이지가 하나였기 때문에 모든 로직이 평평하게 놓여 있었다.

### After
```
dash_app/
├── app.py                  # use_pages=True 엔트리 + 루트 stores
├── config.py               # 상수 (SIDO_OPTIONS, PAGES, CHIP_PROMPTS)
├── theme.py                # 유지
├── db.py                   # 엔진 + geojson 로더 (축소)
├── charts.py               # 유지
│
├── pages/                  # dash.register_page 기반 7페이지
│   ├── home.py             # "/"
│   ├── region.py           # "/region"
│   ├── complex.py          # ... 이하 skeleton
│   ├── gap.py
│   ├── invest.py
│   ├── insight.py
│   └── about.py
│
├── components/             # 재사용 UI 팩토리
│   ├── sidebar.py          # 페이지 네비 + filter_panel 조립
│   ├── filter_panel.py     # 시도·시군구·면적·거래유형·기간
│   ├── kpi_card.py         # term 자동 래핑 KPI 타일
│   ├── term_tip.py         # GLOSSARY 툴팁
│   ├── empty_state.py      # Phase C.0 추가
│   ├── status_banner.py    # Phase C.0 추가
│   ├── formatters.py       # format_won/percent/ppm2
│   ├── choropleth_map.py   # dash-leaflet 래퍼
│   ├── ranking_table.py    # dash-ag-grid 래퍼
│   └── chat_panel/         # 채팅 (Phase D 에서 재작성)
│
├── callbacks/              # 전역 콜백
│   ├── filters.py          # Phase C.3 에서 분리 신설
│   ├── navigation.py
│   └── theme.py
│
├── queries/                # DB 접근 계층
│   ├── rt_queries.py       # 국토부 실거래
│   ├── nv_queries.py
│   ├── mapping_queries.py
│   ├── metrics_queries.py
│   └── news_queries.py
│
└── glossary/
    └── terms.py            # 12개 용어 사전
```

### 이관 전략

Phase A+B 지침: **"로직 변경 없이 물리 이동만"**. 이 원칙을 지킨 덕에 Git diff 가 축소되어 리뷰가 간단해졌다. 예외는:

1. `chat_components()` — 스펙 6장에서 완전 재작성 예정이라 일단 `layout.py` 로 옮기고 로직 유지, Phase D 에서 대체.
2. `db.py` — 스펙 8.4 는 `shared.db.get_engine()` 의 "얇은 래퍼" 로 축소 요구. 하지만 기존 Dash 용 엔진은 `pool_size=20 / statement_timeout=60s` 등 운영 튜닝이 들어가 있어 그대로 단순화하면 회귀. 타협: Phase A+B 에서는 이 파일을 유지하고 쿼리 함수만 `queries/rt_queries.py` 로 분리. 교재에서 "스펙은 이상, 운영 제약은 현실" 사례로 기록.

---

## 3. 의존성 추가

`pyproject.toml` 에 한 번에 추가:

```toml
dependencies = [
    ...
    "dash",
    "dash-leaflet",              # dl.Map / dl.GeoJSON — choropleth 구현
    "dash-ag-grid",              # 대용량 테이블
    "dash-mantine-components",   # TermTip 초기 버전에 dmc.Tooltip 사용 (후에 교체)
    "cachetools",                # metrics_queries TTL 캐시
    ...
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff",
    "mypy",
    "dash[testing]",
    "selenium",
    "testcontainers[postgres]",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]  # dash_app 패키지 직접 import 가능

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.mypy]
files = ["dash_app"]
exclude = ["agents/", "pipeline/"]  # Phase A+B 는 agents/pipeline 미수정
follow_imports = "silent"
ignore_missing_imports = true
```

`uv sync` 한 번에 설치 완료. 총 52 패키지 신규.

---

## 4. 만난 문제와 해결

### 4.1 `shared.db.get_engine()` 이 매 호출마다 신규 엔진 생성

`shared/db.py` 의 구현:
```python
def get_engine() -> Engine:
    return create_engine(DATABASE_URL)
```

스펙 8.4 는 `dash_app/db.py` 를 이 함수의 얇은 래퍼로 만들라고 한다. 하지만 Dash 웹 계층에서 콜백마다 엔진을 새로 만들면 pool 이 없어 매번 connection 을 짧은 시간에 재생성 → 동시성 저하 + 간혹 `too many connections`.

**해결**: `dash_app/db.py` 를 유지하되 `queries/rt_queries.py` 에서 `get_engine()` 이라는 동일 이름으로 재노출. 외부에서는 `from dash_app.db import get_engine` 만 쓰면 되고, 내부적으로는 pooled singleton.

```python
# dash_app/db.py
_engine: Engine | None = None

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            pool_size=20, max_overflow=20,
            pool_pre_ping=True, pool_recycle=1800,
            connect_args={"options": "-c statement_timeout=60000"},
        )
    return _engine
```

`statement_timeout=60000` (ms) 는 메모리 파일 `feedback_pg_statement_timeout.md` 에 "dev-side 엔진은 60s 제한" 으로 남은 원칙을 따른 것. Dash 콜백이 실수로 무거운 쿼리를 던져도 backend 에서 자동 종료되어 좀비 backend 가 남지 않는다.

### 4.2 `mypy` 가 agents/ 를 따라 들어가며 에러 폭발

`dash_app` 을 타겟으로 했지만 `from agents.graph import create_supervisor_graph` 같은 import 때문에 mypy 가 agents 모듈 전체를 검사하고 수많은 에러 발생 (타입 힌트 부재, 미설치 stub 등).

**해결**: `tool.mypy` 에 `follow_imports = "silent"` + `exclude = ["agents/", "pipeline/"]` 추가. 스펙 0.2 의 "agents/ 수정 금지" 와 일관.

### 4.3 TermTip 에 `dmc.Tooltip` 사용 — 렌더 실패

스펙 5.2 는 `dash_mantine_components.Tooltip` 기반 구현을 제안. 문제는 `dmc.*` 컴포넌트가 `MantineProvider` 로 감싸야 렌더된다는 것. 앱 전체를 Provider 로 감싸면 기존 dark theme 토큰이 Mantine 기본 팔레트와 충돌.

**Phase A+B 시점의 임시 해결**: 그냥 dmc.Tooltip 을 쓰되 Provider 를 안 둔 상태로 커밋. → Phase D 에서 실제 렌더링 버그로 드러남 (라벨이 빈 공간으로 표시) → native `title` 속성으로 교체.

교재 포인트: **외부 라이브러리의 암묵적 의존성** (이 경우 Provider) 은 체크해야 한다는 사례.

### 4.4 `prevent_initial_callbacks="initial_duplicate"` 타입 오류

Dash 는 `bool` 을 stub 에 선언하지만 실제로는 `"initial_duplicate"` 문자열도 허용. mypy 가 불평.

**해결**: 해당 라인에 `# type: ignore[arg-type]`. Dash 스텁이 업데이트될 때까지 임시.

---

## 5. Phase C.0 — DDL + 쿼리 모듈 + 공통 컴포넌트

### 5.1 DDL 추가 (`scripts/init_db.py`)

사용자 결정:
- `news_articles` 테이블 신설 (Q1:b — CLAUDE.md 의 "뉴스 저장 안 함" 정책 변경)
- `mv_metrics_by_sgg` / `mv_metrics_by_complex` MV 신설 (Q2:b)
- News ETL 을 `run_daily.py` 에 통합

`news_articles` 스키마:
```sql
CREATE TABLE IF NOT EXISTS news_articles (
    id              BIGSERIAL PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,    -- Naver originallink 로 중복 제거
    title           TEXT NOT NULL,
    description     TEXT,
    body            TEXT,                    -- 본문 스크랩 (실패 시 NULL)
    publisher       VARCHAR(100),
    published_at    TIMESTAMPTZ,
    scope           VARCHAR(20),             -- regional | national | policy | unknown
    sido_name       VARCHAR(20),
    sgg_name        VARCHAR(50),
    category        VARCHAR(30),             -- market | policy | rates | other
    ad_filtered     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

MV 두 개:

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_metrics_by_sgg AS
-- 매매 + 전세 집계를 하나의 윈도우로, FILTER 절로 기간별 분기
SELECT sido_name AS sido, sgg_name AS sgg,
       COUNT(*) FILTER (WHERE deal_date >= CURRENT_DATE - INTERVAL '6 months')  AS trade_count_6m,
       ...
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deal_amount / NULLIF(exclusive_area, 0))
         FILTER (WHERE deal_date >= CURRENT_DATE - INTERVAL '6 months' AND exclusive_area > 0)
         AS median_ppm2_6m,
       ...
FROM rt_trade JOIN rt_complex ON ...
GROUP BY sido_name, sgg_name;

CREATE UNIQUE INDEX uq_mv_metrics_by_sgg ON mv_metrics_by_sgg (sido, sgg);
```

UNIQUE INDEX 가 있어야 `REFRESH MATERIALIZED VIEW CONCURRENTLY` 가능. `run_daily.py` 에 refresh 단계 추가:

```python
for name in ("mv_metrics_by_sgg", "mv_metrics_by_complex"):
    try:
        with engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {name}")
            )
    except Exception:
        # 최초 실행 시 row 가 적거나 unique index 가 없으면 CONCURRENTLY 실패 → fallback
        with engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f"REFRESH MATERIALIZED VIEW {name}")
            )
```

### 5.2 `pipeline/collect_news.py` — Naver News API → news_articles

전략:
- 수도권 시도별 + 전국 정책 + 금리 키워드로 검색 (총 ~15개 쿼리)
- 광고성 필터 (`_is_ad_like`): `[광고]`/`[AD]` 브라켓, 모델하우스/분양 문의 등 키워드
- 지역 태깅 (`_detect_region`): `rt_complex` 의 sgg_name 리스트와 제목·본문 매칭 → `regional` + sgg 저장, 없으면 `national`/`unknown`
- `ON CONFLICT (url) DO NOTHING` 으로 멱등 upsert

**agents 의존성 회피**: `agents/news_agent.py` 에 비슷한 헬퍼(`_search_naver_news`, `_scrape_article` 등) 가 있지만 `_` 로 시작하는 private 함수. 스펙 0.2 의 "agents 수정 금지" 를 준수하면서 깔끔한 재사용 어렵다고 판단 → pipeline/collect_news.py 를 자립 구현. 30줄 정도의 Naver API 호출 코드는 중복을 감수.

### 5.3 공통 컴포넌트 5종

| 컴포넌트 | 파일 | 설명 |
|---|---|---|
| `format_won/percent/count/ppm2` | `components/formatters.py` | 만원→억 변환, 천단위 콤마, NaN/None handling |
| `EmptyState` | `components/empty_state.py` | 데이터 없음 상태 표준 UI |
| `StatusBanner` | `components/status_banner.py` | 상단 요약 뱃지 (spec 3.6 insight 페이지용) |
| `ChoroplethMap` | `components/choropleth_map.py` | dash-leaflet 기반 시군구 맵. Phase C.1 에서 대폭 수정 |
| `RankingTable` | `components/ranking_table.py` | dash-ag-grid 래퍼 + 페이지네이션/정렬/필터 |

#### `ChoroplethMap` 초기 설계 (Phase A+B 시점)

```python
def prepare_choropleth_data(values_by_sgg, color_scale, selected_sgg, sido) -> dict:
    # 각 feature 의 properties 에 fillColor 직접 주입
    # 스타일 JS 함수가 properties.fillColor 를 읽어 렌더
```

콜백은 `dl.GeoJSON.data` prop 을 업데이트하는 식. → **Phase C.1 에서 치명적 이슈 발견** (data 업데이트 시 기존 layer 가 제거되지 않고 겹쳐 그려져 대각선 아티팩트 발생). `hideout` 패턴으로 재설계 (Phase 10 devlog 참조).

---

## 6. 코드 변경 규모

| 지표 | 값 |
|---|---:|
| Phase A+B 커밋 diff | +1,810 / -? (9 commits 통합) |
| 신규 Python 파일 | 21 |
| 삭제 Python 파일 | 2 (`components.py`, `callbacks.py` 통합됨) |
| 신규 테스트 | 6 (기본 smoke + glossary) |
| 테스트 통과 | `pytest 6/6` / `ruff ✓` / `mypy ✓ (30 files)` |

---

## 7. 남은 과제 / Phase C 로 넘어간 것

- **실데이터 기반 페이지 구현** — region/gap/invest/complex/insight 스켈레톤 → 실 컨텐츠 (Phase 10)
- **홈 페이지 업그레이드** — Phase A+B 에서 기존 로직 그대로 이관만. 스펙 3.1 의 신규 구성은 Phase C.3 에서 교체.
- **TermTip 렌더 버그** — MantineProvider 미설정 이슈 (Phase 11 에서 native title 로 전환)
- **ChoroplethMap 의 data-update 아티팩트** — Phase C.1 에서 발견·수정

---

## 8. 교재 포인트 요약

1. **"물리 이동만" 원칙** 이 대규모 리팩토링에서 리뷰 비용을 줄인다.
2. **운영 튜닝(pool / statement_timeout)** 은 스펙의 "단순화" 지시가 있어도 회귀 방지를 위해 유지. 스펙보다 운영 현실이 우선.
3. **외부 라이브러리 의존성** (Mantine Provider) 은 처음엔 그냥 쓰다가 버그로 드러난다 — 조기에 "렌더되는가" 테스트 필요.
4. **`private` 함수 재사용 회피**: 스펙이 수정 금지 영역으로 지정한 모듈의 `_` 프리픽스 함수를 import 하는 건 coupling 증가. 30줄 정도는 재구현이 나음.
5. **MV + CONCURRENTLY refresh** 패턴: unique index + fallback 이 핵심.
