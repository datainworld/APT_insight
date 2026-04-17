# Phase 1: 프로젝트 초기 설정

> 날짜: 2026-04-16

## 목표

Python 3.13 + uv 기반 프로젝트 골격을 세우고, DB 스키마를 확정하고 초기화한다.

## 작업 내역

### 1-1. 저장소 초기화

- `pyproject.toml` — 개발 계획서 9. 의존성 기반
- `.env.example` — 환경변수 템플릿
- `.gitignore` — Python + .env + uploads/ + __pycache__

`uv sync` 결과: 179개 패키지 설치 성공.

### 1-2. shared/ 모듈

- `shared/config.py` — 환경변수 로드 (DATABASE_URL, LLM_PROVIDER, API 키 등)
- `shared/db.py` — SQLAlchemy 엔진 팩토리

**설계 결정:** DATABASE_URL을 `postgresql+psycopg://` 형식으로 고정. 이유: PGVector와 SQLAlchemy가 모두 psycopg v3 드라이버를 요구함. 단, SQL 에이전트의 SQLDatabase는 이 형식 그대로 사용 가능.

### 1-3. docker-compose.yml

PostgreSQL 18 + pgvector 0.8.0 이미지 사용. 로컬에 이미 PostgreSQL이 설치되어 있어서 로컬 개발은 기존 DB 사용.

### 1-4. DB 스키마 초기화 (`scripts/init_db.py`)

초안에서는 8개 테이블 생성했으나, devlog #8(RAG = PDF 벡터 검색)의 구현 방식을 확정한 후 `pdf_document`/`pdf_chunk` 테이블은 제거. LangChain PGVector가 자체 관리하는 `langchain_pg_embedding` 테이블을 사용하기로 결정.

**최종 테이블 (6개):**
| 테이블 | 설명 |
|--------|------|
| `rt_complex` | 국토부 아파트 단지 |
| `rt_trade` | 매매 실거래 |
| `rt_rent` | 전월세 실거래 |
| `nv_complex` | 네이버 단지 |
| `nv_listing` | 네이버 매물 |
| `complex_mapping` | 국토부↔네이버 단지 매핑 |

**Text-to-SQL 최적화 (devlog #5 반영):**
- 모든 테이블에 `COMMENT ON TABLE` 추가
- 핵심 테이블의 모든 컬럼에 `COMMENT ON COLUMN` 추가 (단위, FK 관계, enum 값 포함)
- 복합 인덱스 (apt_id + deal_date 등) 추가

## 검증

| 항목 | 결과 |
|------|------|
| `uv sync` | 성공 (179개 패키지) |
| DB 연결 테스트 | `check_connection()` → True |
| 테이블 생성 | 6개 테이블 + pgvector extension 확인 |
| 컬럼 COMMENT | 36개 컬럼에 메타데이터 적용 확인 |

## 다음 단계

Phase 2: 데이터 파이프라인 이관
