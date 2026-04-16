# Phase 0: 프로젝트 기획 및 계획 수립

> 날짜: 2026-04-16

## 배경

'공공데이터 활용 with AI' 교재의 advance 버전을 제작하기 위해,
교재 작성에 앞서 목표 시스템을 먼저 개발하기로 했다.

기존에 운영 중인 두 프로젝트가 있다:
- **APT_data_pipeline** (`d:/Work/APT_data_pipeline/`) — 데이터 수집·가공 파이프라인
- **APT_insight_03** (`d:/Work/APT_insight_03/`) — LangChain 기반 AI 에이전트 + Chainlit UI

이 두 프로젝트를 하나로 통합하되, 여러 측면에서 업그레이드한다.

## 기존 시스템 분석

### APT_data_pipeline
- 수도권 아파트 매매+전월세+네이버 매물+뉴스를 수집·가공
- PostgreSQL에 7개 테이블 (apt_basic, apt_detail, apt_trade, apt_rent, naver_complex, naver_listing, complex_mapping) + news_articles
- Hostinger VPS에서 Dokploy로 스케줄 실행 (00:00 네이버, 04:00 업데이트, 05:00 뉴스)
- 이어받기 패턴, 적응형 딜레이, 체크포인트 등 운영 안정성 장치 구현됨

### APT_insight_03
- LangChain 1.x `create_agent()` 기반 SQL/RAG 에이전트
- Supervisor가 서브에이전트(SQL, RAG) 호출
- RAG는 PGVector에 저장된 뉴스 기사 벡터 검색
- Chainlit 웹 UI (텍스트 스트리밍 + cl.Step)
- LLM: Gemini 3 Flash Preview

## 주요 의사결정

### 1. 뉴스 수집 파이프라인 제거
- **결정:** `collect_news.py` 삭제, `news_articles` 테이블 삭제
- **이유:** 뉴스는 축적하지 않고, News 에이전트가 실시간으로 네이버 검색 API를 호출하여 최신 뉴스를 제공
- **영향:** 스케줄에서 05:00 뉴스 수집 제거, DB 테이블 1개 감소

### 2. apt_detail 테이블 제거
- **결정:** K-Apt 상세 정보(세대수, 주차, 지하철 등) 수집/저장하지 않음
- **이유:** 핵심 분석 대상은 실거래가와 매물. 단지 상세 정보는 부가적이고, 수집에 API 호출이 많이 소모됨
- **영향:** collect_rt.py에서 K-Apt API 호출 부분 제거, 스키마 단순화

### 3. 테이블 명명 규칙 — 소스 prefix
- **결정:** rt_complex, rt_trade, rt_rent (국토부) / nv_complex, nv_listing (네이버) / pdf_document, pdf_chunk (문서)
- **이유:** 데이터 출처가 명확히 구분되어야 SQL 에이전트와 개발자 모두 혼란이 없음
- **대안 검토:** "기능 prefix" (complex, trade 등)와 "기존 이름 유지" (apt_basic 등)도 검토했으나, 소스 prefix가 가장 직관적

### 4. deal_diff/rate 컬럼 삭제
- **결정:** rt_trade에서 deal_diff, deal_diff_rate 제거. rt_rent에서 deposit_diff, deposit_diff_rate, rental_adjusted_deposit 제거
- **이유:** 파생 컬럼은 저장하지 않고 필요 시 SQL 윈도우 함수로 계산. 저장 공간 절약 + 스키마 단순화
- **SQL 예시:** `LAG(deal_amount) OVER (PARTITION BY apt_id, exclusive_area ORDER BY deal_date)`

### 5. Text-to-SQL 최적화 스키마
- **결정:** 모든 컬럼에 인라인 주석, 테이블 COMMENT, 주요 컬럼 인덱스, enum 값 명시
- **이유:** LLM이 스키마를 읽고 정확한 SQL을 생성하려면 컬럼의 의미·단위·허용값을 알아야 함
- **구체적 조치:**
  - `-- 거래 금액 (단위: 만원)` 같은 인라인 주석
  - `COMMENT ON TABLE rt_trade IS '...'` — LLM이 스키마 도구로 읽을 수 있음
  - `idx_rt_trade_apt_date` 같은 복합 인덱스 — 자주 쿼리되는 패턴 지원

### 6. 네이버 매물 수집 시간 단축
- **채택:** 지역별 병렬화 (서울/경기/인천 동시 수집) + 워커 수 최적화 (5→8~10)
- **보류:** "변경분만 수집"은 가격만 변경된 매물을 놓칠 리스크가 있어 보류
- **보류:** 쿠키 풀은 복수 계정 운영 부담 + 네이버 정책 리스크로 보류

### 7. LLM 교체 용이 구조
- **결정:** `LLM_PROVIDER`와 `LLM_MODEL` 환경변수로 LLM을 교체
- **이유:** Gemini 3.1 Flash-Lite가 기본이지만, 다른 모델로 쉽게 전환 가능해야 함
- **구현:** `agents/config.py`의 `get_llm()` 함수가 provider에 따라 다른 ChatModel 반환

### 8. RAG = PDF 문서 검색
- **결정:** RAG 에이전트는 뉴스가 아닌 사용자가 업로드한 PDF 문서를 벡터 검색
- **이유:** 뉴스는 실시간 검색(News Agent)으로 처리. RAG는 부동산 정책 보고서, 시장 분석 리포트 등 PDF 기반
- **구현:** Chainlit 파일 업로드 → PyMuPDF 텍스트 추출 → 청킹 → Gemini 임베딩 → pdf_chunk 테이블 저장

## 생성된 산출물

1. `docs/DEVELOPMENT_PLAN.md` — 개발 계획서 (초안 → 리뷰 → 수정)
2. `CLAUDE.md` — 프로젝트 컨텍스트 문서
3. `docs/devlog/phase0_planning.md` — 이 문서

## 다음 단계

Phase 1: 프로젝트 초기 설정 (pyproject.toml, shared/, docker-compose, DB 스키마)
→ 시작 전 사전 협의 필요
