# APT_insight_04 개발 계획서

> 작성일: 2026-04-16
> 상태: 초안

---

## 1. 프로젝트 개요

수도권(서울/경기/인천) 아파트 실거래가·매물·뉴스 데이터를 수집·분석하고,
LangGraph 기반 멀티 에이전트로 자연어 질의·문서 검색·실시간 뉴스 검색을 제공하는 시스템.

### 1.1 기존 시스템과의 차이

| 항목 | APT_data_pipeline + APT_insight_03 | APT_insight_04 |
|------|-----------------------------------|----------------|
| 데이터 | 매매+전월세+네이버매물+뉴스 | 동일 (코드 통합) |
| DB | PostgreSQL (파이프라인 별도 프로젝트) | PostgreSQL + PGVector (단일 프로젝트) |
| Agent 프레임워크 | LangChain `create_agent()` | **LangGraph `StateGraph` + SubGraph** |
| Agent 구성 | SQL + RAG(뉴스 벡터검색) | **SQL + RAG(PDF) + News(실시간검색)** |
| LLM | Gemini 3 Flash Preview | **Gemini 3.1 Flash-Lite** (교체 용이) |
| 모니터링 | 없음 | **LangSmith** |
| UI | Chainlit (텍스트) | **Chainlit + Plotly (차트) + PDF 업로드** |
| 배포 | Dokploy (2개 프로젝트 분리) | **Dokploy (단일 프로젝트)** |

### 1.2 핵심 설계 원칙

1. **단일 저장소** — 파이프라인과 에이전트를 하나의 프로젝트로 통합
2. **LLM 교체 용이** — config에서 모델명만 바꾸면 전체 에이전트에 반영
3. **기존 코드 최대 활용** — APT_data_pipeline의 파이프라인, APT_insight_03의 에이전트 구조를 가져와 리팩토링

> **[리뷰]** 1. 프로젝트 개요:
>뉴스는 수집하지 않음 
> 기존 코드 활용하되, 간결하고 이해하기 쉽고 재사용 가능하게 리팩토링하여야 함

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hostinger VPS (Dokploy)                       │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐  │
│  │ pipeline worker  │  │ app (Chainlit)                       │  │
│  │ (sleep infinity) │  │                                      │  │
│  │                  │  │  Web UI ──→ Supervisor Graph          │  │
│  │ Scheduler:       │  │              ├─ SQL SubGraph          │  │
│  │  00:00 naver     │  │              ├─ RAG SubGraph (PDF)    │  │
│  │  04:00 update    │  │              ├─ News SubGraph         │  │
│  │  05:00 news      │  │              └─ Chart Tool (Plotly)   │  │
│  └────────┬─────────┘  └──────────────┬───────────────────────┘  │
│           │                           │                          │
│  ┌────────▼───────────────────────────▼──────────────────────┐  │
│  │              PostgreSQL 18 + PGVector                      │  │
│  │                                                            │  │
│  │  apt_basic · apt_detail · apt_trade · apt_rent             │  │
│  │  naver_complex · naver_listing · complex_mapping           │  │
│  │  news_articles (+ vector)                                  │  │
│  │  pdf_documents (+ vector)                                  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  uploads/   (PDF 파일 저장)                                 │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │
         └──→ LangSmith (외부 SaaS, trace/eval)
```

> **[리뷰]** 2. 시스템 아키텍처:
>News  는 저장하지 않음 
> 

---

## 3. 디렉토리 구조

```
APT_insight_04/
├── pipeline/
│   ├── collect_rt.py              # 국토부 매매+전월세 (서울/경기/인천, 36개월)
│   ├── collect_naver.py           # 네이버 매물 (매매/전세/월세)
│   ├── collect_news.py            # 뉴스 수집 + 벡터DB 적재
│   ├── update_daily.py            # 증분 갱신 + 매핑 + DB 마이그레이션
│   └── utils.py                   # 공통 유틸리티 (API, CSV, DB)
├── agents/
│   ├── config.py                  # LLM·DB·벡터스토어 팩토리 (모델 교체 지점)
│   ├── graph.py                   # Supervisor StateGraph 정의
│   ├── sql_agent.py               # SQL SubGraph
│   ├── rag_agent.py               # RAG SubGraph (PDF 벡터 검색)
│   ├── news_agent.py              # News SubGraph (실시간 뉴스 검색)
│   └── chart_tools.py             # Plotly 차트 생성 도구
├── shared/
│   ├── config.py                  # 환경변수 로드
│   └── db.py                      # SQLAlchemy 엔진 + 세션 팩토리
├── app.py                         # Chainlit 웹 서버
├── uploads/                       # 사용자 업로드 PDF 저장
├── docs/
│   └── DEVELOPMENT_PLAN.md        # 이 문서
├── Dockerfile
├── docker-compose.yml             # postgres + app + pipeline
├── .env.example
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

> **[리뷰]** 3. 디렉토리 구조:
>collect_news.py  필요없음
> 

---

## 4. 기술 스택

| 레이어 | 기술 | 버전 |
|--------|------|------|
| 언어 | Python | 3.13 |
| 패키지 관리 | uv | latest |
| LLM | Google Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` |
| Embedding | Gemini Embedding | `gemini-embedding-001` |
| Agent 프레임워크 | LangGraph | 1.x |
| Agent 기반 | LangChain | 1.x |
| 모니터링 | LangSmith | latest |
| DB | PostgreSQL | 18 |
| Vector | PGVector | 0.4+ |
| PDF 처리 | PyMuPDF (fitz) | latest |
| 웹 UI | Chainlit | latest |
| 차트 | Plotly | latest |
| HTTP (공공API) | requests | latest |
| HTTP (네이버) | curl_cffi | latest |
| 지오코딩 | Kakao API | v2 |
| 배포 | Dokploy (Docker Swarm) | latest |
| 서버 | Hostinger VPS | Ubuntu 24.04 |

> **[리뷰]** 4. 기술 스택:
> 
> 

---

## 5. DB 스키마

기존 APT_data_pipeline 스키마를 그대로 유지하고, PDF 문서 테이블을 추가한다.

### 5.1 기존 테이블 (변경 없음)

```sql
-- 단지 기본 정보
apt_basic (
    apt_id          TEXT PRIMARY KEY,
    apt_name        TEXT,
    build_year      TEXT,
    road_address    TEXT,
    jibun_address   TEXT,
    latitude        FLOAT,
    longitude       FLOAT,
    admin_dong      TEXT
)

-- 단지 상세 정보
apt_detail (
    complex_id      TEXT PRIMARY KEY,
    apt_id          TEXT REFERENCES apt_basic,
    complex_name    TEXT,
    household_count INTEGER,
    approval_date   TEXT,
    total_parking_count INTEGER,
    subway_station  TEXT,
    subway_line     TEXT
)

-- 매매 실거래
apt_trade (
    id              SERIAL PRIMARY KEY,
    apt_id          TEXT REFERENCES apt_basic,
    apartment_name  TEXT,
    deal_date       DATE,
    deal_amount     FLOAT,       -- 만원
    exclusive_area  FLOAT,       -- ㎡
    floor           TEXT,
    buyer_type      TEXT,        -- 개인/법인/공공기관/기타
    dealing_type    TEXT,        -- 중개거래/직거래
    deal_diff       FLOAT,
    deal_diff_rate  FLOAT
)

-- 전월세 실거래
apt_rent (
    id              SERIAL PRIMARY KEY,
    apt_id          TEXT REFERENCES apt_basic,
    apartment_name  TEXT,
    deal_date       DATE,
    deposit         FLOAT,       -- 만원
    monthly_rent    FLOAT,       -- 만원
    rental_adjusted_deposit FLOAT,
    exclusive_area  FLOAT,
    floor           TEXT,
    contract_type   TEXT,        -- 신규/갱신
    deposit_diff    FLOAT,
    deposit_diff_rate FLOAT
)

-- 네이버 단지 정보
naver_complex (
    complex_no      TEXT PRIMARY KEY,
    complex_name    TEXT,
    sido_name       TEXT,
    sgg_name        TEXT,
    dong_name       TEXT,
    latitude        FLOAT,
    longitude       FLOAT
)

-- 네이버 매물
naver_listing (
    article_no      TEXT PRIMARY KEY,
    complex_no      TEXT REFERENCES naver_complex,
    trade_type      TEXT,        -- A1(매매)/B1(전세)/B2(월세)
    exclusive_area  FLOAT,
    initial_price   FLOAT,
    current_price   FLOAT,
    rent_price      FLOAT,
    floor_info      TEXT,
    direction       TEXT,
    confirm_date    DATE,
    is_active       BOOLEAN
)

-- 단지 매핑
complex_mapping (
    apt_id          TEXT REFERENCES apt_basic,
    naver_complex_no TEXT REFERENCES naver_complex
)

-- 뉴스 기사 (벡터 검색)
news_articles (
    id              SERIAL PRIMARY KEY,
    title           TEXT,
    url             TEXT UNIQUE,
    description     TEXT,
    body            TEXT,
    source          TEXT,
    pub_date        TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    embedding       vector(768)
)
```

### 5.2 신규 테이블

```sql
-- PDF 문서 (사용자 업로드, 벡터 검색)
pdf_documents (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    uploaded_at     TIMESTAMP DEFAULT NOW(),
    total_pages     INTEGER,
    total_chunks    INTEGER
)

-- PDF 청크 (RAG 검색 단위)
pdf_chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER REFERENCES pdf_documents ON DELETE CASCADE,
    chunk_index     INTEGER,
    content         TEXT,
    page_number     INTEGER,
    embedding       vector(768)
)
```

> **[리뷰]** 5. DB 스키마:
>apt_detail 테이블 없음
 테이블 이름은 일관성 있게 rename 필요
> 

---

## 6. 컴포넌트 상세 설계

### 6.1 파이프라인 (pipeline/)

기존 APT_data_pipeline 코드를 가져와 단일 프로젝트에 통합한다.
로직 변경 없이 import 경로와 config 참조만 수정.

| 파일 | 원본 | 역할 |
|------|------|------|
| `utils.py` | `pipeline/utils.py` | API 호출, CSV, DB 유틸리티 |
| `collect_rt.py` | `collect_and_process.py` | 단지코드 + 기본/상세 + 매매/전월세 수집·가공 |
| `collect_naver.py` | `collect_naver_listing.py` | 네이버 매물 수집 (매매/전세/월세) |
| `collect_news.py` | `collect_news.py` | 뉴스 수집 + 임베딩 + 벡터DB |
| `update_daily.py` | `update_and_migrate.py` | 일일 증분 갱신 + DB 마이그레이션 |

### 6.2 에이전트 (agents/)

#### config.py — LLM 교체 지점

```python
# .env에서 모델명을 읽어 LLM 인스턴스를 생성한다.
# LLM_PROVIDER=google, LLM_MODEL=gemini-3.1-flash-lite 가 기본값.
# OpenAI나 Anthropic으로 교체 시 provider와 model만 변경하면 된다.

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "google")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")

def get_llm():
    if LLM_PROVIDER == "google":
        return ChatGoogleGenerativeAI(model=LLM_MODEL)
    elif LLM_PROVIDER == "openai":
        return ChatOpenAI(model=LLM_MODEL)
    elif LLM_PROVIDER == "anthropic":
        return ChatAnthropic(model=LLM_MODEL)
```

#### graph.py — Supervisor (LangGraph StateGraph)

```
                    ┌──────────┐
                    │  START   │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  router  │  ← 질문 분류
                    └──┬─┬─┬───┘
                       │ │ │
          ┌────────────┘ │ └────────────┐
          │              │              │
     ┌────▼────┐  ┌─────▼─────┐  ┌─────▼─────┐
     │sql_agent│  │ rag_agent │  │news_agent │
     └────┬────┘  └─────┬─────┘  └─────┬─────┘
          │              │              │
          └──────────────┼──────────────┘
                         │
                    ┌────▼─────┐
                    │synthesize│  ← 결과 종합 + 차트 생성 판단
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │   END    │
                    └──────────┘
```

**State 스키마:**
```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    next: str                    # 라우팅 대상
    sql_result: str | None       # SQL 에이전트 결과
    rag_result: str | None       # RAG 에이전트 결과
    news_result: str | None      # 뉴스 에이전트 결과
    chart_data: dict | None      # Plotly 차트용 데이터
```

**라우팅 규칙 (router 노드):**
- 수치/통계/특정 단지 질문 → `sql_agent`
- PDF 문서 관련 질문 → `rag_agent`
- 시장 동향/최신 뉴스 질문 → `news_agent`
- 복합 질문 → 병렬 실행 (Send API)

#### sql_agent.py — SQL SubGraph

기존 APT_insight_03의 SQL 에이전트 구조 유지.
변경: `create_agent()` → LangGraph `StateGraph`로 래핑.
시스템 프롬프트에 DB 스키마·조인 경로·날짜 범위를 포함.

#### rag_agent.py — RAG SubGraph (PDF)

- 사용자가 업로드한 PDF에서 유사 청크를 검색
- PGVector의 `pdf_chunks` 테이블에서 similarity search
- 출처(파일명, 페이지)를 반드시 포함하여 응답

#### news_agent.py — News SubGraph (실시간)

- 네이버 검색 API로 실시간 뉴스 검색
- 기사 본문 스크래핑 + 요약
- 기존 `collect_news.py`의 검색/스크래핑 함수를 재사용

#### chart_tools.py — Plotly 차트 도구

- SQL 에이전트의 쿼리 결과(DataFrame)를 받아 Plotly Figure 생성
- 차트 유형: 시계열 라인, 가격 분포 바, 지역 비교 바, 산점도
- Chainlit의 `cl.Plotly(figure)`로 렌더링

### 6.3 웹 UI (app.py)

Chainlit 기반. 기존 APT_insight_03의 `app.py` 구조를 확장.

**추가 기능:**
1. **PDF 업로드** — Chainlit 파일 업로드 → PyMuPDF로 텍스트 추출 → 청킹 → 임베딩 → pdf_chunks 저장
2. **Plotly 차트** — 에이전트 응답에 차트 데이터가 포함되면 인터랙티브 차트 렌더링
3. **에이전트 단계 표시** — 기존과 동일 (cl.Step으로 중간 과정 노출)

### 6.4 모니터링 (LangSmith)

```python
# .env
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=apt-insight-04
LANGSMITH_TRACING=true
```

- 모든 LangGraph 호출이 자동으로 LangSmith에 트레이스됨
- 별도 코드 불필요 — 환경변수 설정만으로 활성화

> **[리뷰]** 6. 컴포넌트 상세 설계:
> 
>기존 코드 재활용할 때에는 간결하고 이해하기 쉽고 재사용 가능하게 리팩토링하여야 함 
코딩 이전에 나하고 반드시 사전 협의를 해야 함
---

## 7. 개발 단계

### Phase 1: 프로젝트 초기 설정

| # | 작업 | 검증 |
|---|------|------|
| 1-1 | 저장소 초기화 (pyproject.toml, .env.example, .gitignore) | `uv sync` 성공 |
| 1-2 | shared/ 모듈 작성 (config.py, db.py) | DB 연결 테스트 통과 |
| 1-3 | docker-compose.yml (postgres + pgvector) | `docker compose up` → 로컬 DB 접속 확인 |
| 1-4 | DB 스키마 초기화 스크립트 (CREATE TABLE + pgvector extension) | 모든 테이블 생성 확인 |

### Phase 2: 데이터 파이프라인 이관

| # | 작업 | 검증 |
|---|------|------|
| 2-1 | pipeline/utils.py 이관 (import 경로 수정) | 단위 함수 호출 성공 |
| 2-2 | pipeline/collect_rt.py 이관 | 테스트 수집(1개 구, 1개월) 성공 |
| 2-3 | pipeline/collect_naver.py 이관 | 테스트 수집(1개 단지) 성공 |
| 2-4 | pipeline/collect_news.py 이관 | 뉴스 5건 수집 + 벡터DB 적재 성공 |
| 2-5 | pipeline/update_daily.py 이관 | 증분 갱신 + DB 마이그레이션 성공 |

### Phase 3: 에이전트 개발

| # | 작업 | 검증 |
|---|------|------|
| 3-1 | agents/config.py (LLM 팩토리, provider 교체 구조) | google/openai 두 provider 전환 테스트 |
| 3-2 | agents/sql_agent.py (LangGraph SubGraph) | "강남구 최근 매매 평균가" 질의 응답 확인 |
| 3-3 | agents/rag_agent.py (PDF 벡터 검색) | 테스트 PDF 업로드 → 검색 → 출처 포함 응답 |
| 3-4 | agents/news_agent.py (실시간 뉴스) | "아파트 시장 전망" 질의 → 뉴스 3건 요약 |
| 3-5 | agents/chart_tools.py (Plotly 생성) | DataFrame → Plotly Figure 렌더링 |
| 3-6 | agents/graph.py (Supervisor + 라우팅) | 복합 질문 → 적절한 에이전트 라우팅 확인 |
| 3-7 | LangSmith 연동 | 트레이스 대시보드에서 호출 로그 확인 |

### Phase 4: 웹 UI

| # | 작업 | 검증 |
|---|------|------|
| 4-1 | app.py 기본 구조 (채팅 + 에이전트 연동) | 텍스트 질의 → 응답 표시 |
| 4-2 | PDF 업로드 기능 | 파일 업로드 → 청킹 → DB 저장 → "업로드 완료" 메시지 |
| 4-3 | Plotly 차트 렌더링 | 시계열 질문 → 인터랙티브 차트 표시 |
| 4-4 | 에이전트 단계 표시 (cl.Step) | 중간 과정(SQL 실행, 검색 등) 실시간 노출 |

### Phase 5: 배포

| # | 작업 | 검증 |
|---|------|------|
| 5-1 | Dockerfile 작성 | 로컬 docker build + run 성공 |
| 5-2 | docker-compose.yml (prod 구성) | 로컬 compose up → 전체 시스템 동작 |
| 5-3 | Dokploy 배포 설정 | VPS에서 앱 접근 + 스케줄러 동작 확인 |
| 5-4 | Dokploy Scheduler 등록 | 00:00/04:00/05:00 스케줄 실행 확인 |

> **[리뷰]** 7. 개발 단계:
> 
>>기존 코드 재활용할 때에는 간결하고 이해하기 쉽고 재사용 가능하게 리팩토링하여야 함 
주용한 작업은 나하고 반드시 사전 협의를 해야 함 

---

## 8. 환경변수

```env
# DB
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=apt_insight

# LLM (교체 지점)
LLM_PROVIDER=google
LLM_MODEL=gemini-3.1-flash-lite
GOOGLE_API_KEY=

# Embedding
EMBEDDING_MODEL=gemini-embedding-001

# 공공데이터 API
DATA_API_KEY=

# 카카오 지오코딩
KAKAO_API_KEY=

# 네이버 부동산
NAVER_LAND_COOKIE=

# 네이버 검색 API (뉴스)
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=

# LangSmith
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=apt-insight-04
LANGSMITH_TRACING=true
```

> **[리뷰]** 8. 환경변수:
> 
> 

---

## 9. 의존성

```toml
[project]
name = "apt-insight-04"
requires-python = ">=3.13"

dependencies = [
    # LLM / Agent
    "langchain>=1.0,<2.0",
    "langchain-core>=1.0,<2.0",
    "langgraph>=1.0,<2.0",
    "langchain-google-genai",
    "langchain-community",
    "langchain-postgres",
    "langsmith>=0.3.0",

    # DB
    "sqlalchemy",
    "psycopg[binary]",
    "pgvector",

    # Web UI
    "chainlit",
    "plotly",

    # PDF
    "pymupdf",

    # Pipeline
    "requests",
    "curl-cffi",
    "xmltodict",
    "pandas",
    "python-dateutil",
    "python-dotenv",
    "haversine",
    "thefuzz",
    "beautifulsoup4",

    # Google GenAI (임베딩 직접 호출)
    "google-genai",
]
```

> **[리뷰]** 9. 의존성:
> 
> 

---

## 10. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 공공데이터 API 일일 호출 한도 | 초기 수집 시 수일 소요 | 이어받기 패턴 유지, --skip 옵션 |
| 네이버 쿠키 만료 | 매물 수집 실패 | 주기적 갱신 알림 (이메일) |
| Gemini 3.1 Flash-Lite 미출시/변경 | LLM 호출 실패 | config.py의 provider 교체로 즉시 대응 |
| PGVector 인덱스 성능 | PDF/뉴스 많아지면 검색 느려짐 | HNSW 인덱스 + 주기적 VACUUM |
| Dokploy 웹훅 미작동 | 수동 배포 필요 | 기존과 동일한 수동 절차 유지 |

> **[리뷰]** 10. 리스크 및 대응:
> 
>네이버  매물 데이터 수집에 많은 시간이 걸리니, 시간 단축 전략 필요  
