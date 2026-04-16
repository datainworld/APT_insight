# APT_insight_04 — CLAUDE.md

## 1. 프로젝트 목적

수도권(서울/경기/인천) 아파트 실거래가·매물 데이터를 수집·분석하고,
LangGraph 기반 멀티 에이전트(SQL·RAG·뉴스)로 자연어 질의를 처리하는 시스템.
이 시스템의 개발 과정이 '공공데이터 활용 with AI' advance 교재의 원료가 된다.

---

## 2. 데이터 범위

| 항목 | 범위 |
|------|------|
| **공간** | 서울특별시 (11), 경기도 (41), 인천광역시 (28) |
| **시간** | 현재 기준 과거 36개월 (rolling window) |
| **소스** | 공공데이터포털 (매매+전월세), 네이버 부동산 (매물), 카카오 (지오코딩) |

---

## 3. 기술 스택

| 레이어 | 기술 |
|--------|------|
| 언어 | Python 3.13 |
| 패키지 관리 | uv |
| LLM | Gemini 3.1 Flash-Lite (교체 용이: `LLM_PROVIDER`/`LLM_MODEL` 환경변수) |
| Embedding | Gemini Embedding (`gemini-embedding-001`) |
| Agent | LangGraph 1.x (StateGraph + SubGraph) |
| 모니터링 | LangSmith |
| DB | PostgreSQL 18 + PGVector |
| PDF | PyMuPDF |
| UI | Chainlit + Plotly |
| 배포 | Hostinger VPS + Dokploy (Docker Swarm) |

---

## 4. 프로젝트 구조

```
APT_insight_04/
├── pipeline/
│   ├── collect_rt.py              # 국토부 매매+전월세 수집·가공
│   ├── collect_naver.py           # 네이버 매물 수집 (매매/전세/월세)
│   ├── update_daily.py            # 증분 갱신 + 매핑 + DB 마이그레이션
│   └── utils.py                   # 공통 유틸리티 (API, CSV, DB)
├── agents/
│   ├── config.py                  # LLM·DB·벡터스토어 팩토리
│   ├── graph.py                   # Supervisor StateGraph
│   ├── sql_agent.py               # SQL SubGraph
│   ├── rag_agent.py               # RAG SubGraph (PDF 벡터 검색)
│   ├── news_agent.py              # News SubGraph (실시간 뉴스, DB 저장 없음)
│   └── chart_tools.py             # Plotly 차트 생성
├── shared/
│   ├── config.py                  # 환경변수 로드
│   └── db.py                      # SQLAlchemy 엔진
├── app.py                         # Chainlit 웹 서버
├── uploads/                       # PDF 업로드 저장
├── docs/
│   ├── DEVELOPMENT_PLAN.md        # 개발 계획서
│   └── devlog/                    # 개발 과정 기록 (교재 원료)
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── pyproject.toml
└── CLAUDE.md                      # 이 파일
```

---

## 5. DB 스키마

테이블 명명: 소스 prefix (rt_=국토부, nv_=네이버, pdf_=문서)

| 테이블 | 설명 |
|--------|------|
| `rt_complex` | 국토부 아파트 단지 기본 정보 (위경도, 행정동) |
| `rt_trade` | 매매 실거래가 (deal_amount 단위: 만원) |
| `rt_rent` | 전월세 실거래가 (deposit/monthly_rent 단위: 만원, 월세=0이면 전세) |
| `nv_complex` | 네이버 부동산 단지 정보 |
| `nv_listing` | 네이버 매물 (trade_type: A1=매매, B1=전세, B2=월세) |
| `complex_mapping` | rt_complex ↔ nv_complex 매핑 |
| `pdf_document` | 사용자 업로드 PDF 문서 |
| `pdf_chunk` | PDF 청크 + vector(768) 임베딩 |

**없는 것:** apt_detail (K-Apt 상세정보 미사용), news_articles (뉴스 저장 안 함)

---

## 6. 에이전트 구조

```
Supervisor (StateGraph)
├─ SQL Agent    — DB 7테이블 자연어 질의 (SQLDatabaseToolkit)
├─ RAG Agent    — PDF 벡터 검색 (pdf_chunk, PGVector)
├─ News Agent   — 네이버 검색 API 실시간 뉴스 (DB 저장 없음)
└─ Chart Tool   — Plotly 차트 생성 (cl.Plotly 렌더링)
```

라우팅: router 노드가 질문을 분류 → 적절한 SubGraph로 전달 → synthesize 노드에서 종합

---

## 7. 환경변수 (`.env`)

| 변수 | 용도 |
|------|------|
| `LLM_PROVIDER` / `LLM_MODEL` | LLM 교체 지점 (기본: google / gemini-3.1-flash-lite) |
| `GOOGLE_API_KEY` | Gemini LLM + Embedding |
| `DATA_API_KEY` | 공공데이터포털 실거래가 API |
| `KAKAO_API_KEY` | 카카오 지오코딩 |
| `NAVER_LAND_COOKIE` | 네이버 부동산 매물 수집 (주기적 갱신 필요) |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 네이버 검색 API (News 에이전트용) |
| `POSTGRES_*` | DB 연결 |
| `LANGSMITH_*` | LangSmith 트레이싱 |

---

## 8. 배포

### 서버
- Hostinger VPS, Ubuntu 24.04
- Dokploy (Docker Swarm)

### 스케줄
| 시각 (KST) | 명령 |
|------------|------|
| 00:00 | `python pipeline/collect_naver.py daily` |
| 04:00 | `python pipeline/update_daily.py` |

### 배포 절차
```
1. git push origin main
2. ssh 서버 → git pull
3. docker build + service update
```

---

## 9. 코드 작성 원칙

> **Karpathy Guidelines 스킬을 반드시 적용한다** (`~/.claude/skills/karpathy-guidelines/SKILL.md`)

### Karpathy Guidelines 요약
1. **Think Before Coding** — 가정을 명시하고, 불확실하면 물어보고, 더 단순한 방법이 있으면 제안
2. **Simplicity First** — 요청한 것만 구현, 추측성 추상화/에러 핸들링 금지, 200줄을 50줄로
3. **Surgical Changes** — 요청과 무관한 코드 수정 금지, 기존 스타일 따르기, 자기가 만든 orphan만 정리
4. **Goal-Driven Execution** — 성공 기준 정의 → 검증까지 루프

### 프로젝트 추가 원칙
- 간결하고 이해하기 쉽고 재사용 가능한 코드
- 기존 코드(APT_data_pipeline, APT_insight_03) 리팩토링 시 원본 대비 변경 의도를 명확히
- 환경변수는 `.env`에서 로드, 하드코딩 금지
- 타입 힌트 필수
- API 호출 함수는 실패 시 None 반환 + 상위에서 명시적 처리
- 수집 스크립트는 중단/재개(이어받기) 지원

---

## 10. 개발 과정 문서화

이 시스템의 개발 과정이 advance 교재의 소재다. 모든 사항을 기록한다.

- **위치:** `docs/devlog/phase{N}_{주제}.md`
- **내용:** 의사결정 이유, 만난 문제, 해결 과정, 코드 변경 전후 비교
- **시점:** 각 Phase 시작/완료 시, 주요 결정 시

---

## 11. 참조 프로젝트

| 프로젝트 | 경로 | 용도 |
|---------|------|------|
| APT_data_pipeline | `d:/Work/APT_data_pipeline/` | 파이프라인 원본 코드 |
| APT_insight_03 | `d:/Work/APT_insight_03/` | 에이전트 원본 코드 |

---

## 12. 알려진 이슈

- 공공데이터 API 일일 호출 한도 → 초기 수집 수일 소요 (이어받기 패턴으로 대응)
- 네이버 쿠키 주기적 만료 → 브라우저에서 재추출 필요
- Dokploy GitHub 웹훅 미작동 → 수동 배포 절차

---

## 13. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-04-16 | 프로젝트 초기 설정. 개발 계획서 작성 및 승인. CLAUDE.md 생성. |
