# Phase 3: 멀티 에이전트 개발

> 날짜: 2026-04-16

## 목표

LangGraph StateGraph 기반 멀티 에이전트를 구현한다. Supervisor가 3개 서브에이전트(SQL, RAG, News)를 병렬 호출하고 결과를 종합한다.

## 구조

```
START → query_generator → [sql_node + rag_node + news_node] (병렬) → synthesize → END
```

**State:**
```python
class SupervisorState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    sql_query: str | None       # SQL 에이전트 전용 질의
    rag_query: str | None       # RAG 에이전트 전용 질의
    news_query: str | None      # News 에이전트 전용 질의
    sql_result: str | None
    rag_result: str | None
    news_result: str | None
    chart_data: str | None
```

## 구현 결정

### 에이전트 생성 API

`langchain.agents.create_agent()` 사용 (LangChain 1.x 권장 API). `langgraph.prebuilt.create_react_agent`는 deprecated되었으므로 미사용.

### 쿼리 생성기 (query_generator)

초기 구현은 단순 라우터(sql/rag/news/direct 중 택1)였으나, 요구사항 변경으로 교체:
- 각 에이전트에 맞는 **개별 질의를 LLM이 생성**
- 가급적 3개 에이전트 모두 호출하여 종합 답변 제공
- `conditional_edges`가 리스트 반환 → 병렬 실행

**방어 로직:**
- JSON 파싱 실패 시 원본 질문으로 sql+news 강제 생성
- 3개 모두 null인데 단순 인사가 아니면 sql+news 강제 생성
- synthesize에서 에이전트 결과 없이 답변할 때 "DB 조회 없이는 구체적 수치 답할 수 없음" 안내 (hallucination 방지)

### 서브에이전트 상세

**SQL 에이전트 (`sql_agent.py`):**
- `SQLDatabaseToolkit.get_tools()` 사용
- 시스템 프롬프트에 전체 스키마, 조인 경로, enum 값, 규칙 포함
- `_fetch_date_range()` — DB에서 실제 min/max deal_date 조회 → 프롬프트에 주입
- 평↔㎡ 변환 안내 (1평 = 3.3058㎡, 주요 평형 매핑 표)

**News 에이전트 (`news_agent.py`):**
- 네이버 검색 API로 실시간 뉴스 검색
- BeautifulSoup으로 기사 본문 스크래핑 (2,000자 제한)
- 출처(언론사, 날짜, URL) 포함 답변 강제

**RAG 에이전트 (`rag_agent.py`):**
- PGVector `langchain_pg_embedding` 테이블에서 유사도 검색
- metadata(source, page) 포함 출력
- 결과 없을 시 "업로드된 PDF 문서에서 관련 내용을 찾을 수 없습니다"

**Chart Tools (`chart_tools.py`):**
- Plotly `@tool generate_chart` — line/bar/scatter
- JSON 문자열 반환 → Chainlit의 `cl.Plotly`에서 렌더링

### Synthesize 노드 (출처 명시 강화)

devlog 피드백 반영:
- 각 에이전트 결과 앞에 `[DB 조회 결과]`, `[뉴스 검색 결과]`, `[PDF 검색 결과]` 태그
- 답변에 출처(DB 조회 / 뉴스 / PDF) 명시 강제
- 서브에이전트 결과의 날짜·수치 임의 변경 금지

## LLM 모델

`gemini-3.1-flash-lite`는 아직 존재하지 않아 `gemini-3.1-flash-lite-preview` 사용. `.env`의 `LLM_MODEL`로 제어.

Gemini가 content를 list 형식으로 반환하는 경우 → `_extract_text` 헬퍼로 통일 처리.

## 검증

| 에이전트 | 테스트 질의 | 결과 |
|----------|-----------|------|
| SQL | "강남구 2026년 3월 매매 평균가는?" | 약 21억 1,024만원 |
| News | "아파트 시장 전망" | 뉴스 3건 요약 + 출처 |
| RAG | "부동산 규제 완화 정책" | "업로드된 PDF 없음" 안내 |
| Chart | 바 차트 샘플 | 유효한 Plotly JSON 생성 |
| Supervisor 병렬 | "강남 아파트 전망은?" | 3개 에이전트 동시 호출 확인 |

## 다음 단계

Phase 4: Chainlit 웹 UI
