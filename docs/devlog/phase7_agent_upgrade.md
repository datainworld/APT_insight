# Phase 7: 멀티 에이전트 답변 품질 고도화

> 날짜: 2026-04-18

## 목표

Phase 6까지 구조적 개선(파이프라인 리팩토링, 도메인 연결, 멀티턴 메모리)을 마친 뒤, 실제 질문으로 돌려보니 **답변 품질 자체의 문제**가 드러났다. 이번 Phase는 Supervisor·SQL·News·시각화 전반에 걸쳐 답변 품질을 끌어올리는 데 집중한다.

## 발견된 문제 (출발점)

| # | 증상 | 영향 |
|---|------|------|
| 1 | "강남구 상위 10개 단지와 위치" → 막대그래프만 반환, 지도 아님 | SQL 결과가 자연어 요약이라 위경도 추출 불가 |
| 2 | "강남구 부동산 동향" 답변에 2024년 통계 인용 | 학습지식 환각 |
| 3 | 뉴스가 "2025-03 기사" 기준 답변 | 광고 필터 후 남은 기사가 과거 |
| 4 | 평균 거래액 `1376800.0` / 좌표 `37.5260635520221` | 원본 값 그대로 노출 |
| 5 | "정책이 매물에 미치는 영향" → 국토부 rt_trade 조회 | 네이버 매물 DB 활용 안 됨 |
| 6 | "실거래가 vs 호가 괴리율" 같은 복합 쿼리 실행 실패 | CTE·JOIN 구문 한계 |
| 7 | 컬럼 제목 `apt_name, avg_ask_price (억원)` | 한국어 라벨 아님 |

## 전체 변경 개요 (9건)

1. SQL agent를 LangGraph subgraph로 재설계
2. chart_node 도입 + Plotly로 시각화 통일 (지도 포함)
3. 위치/가격 질문 필수 컬럼 강제 (SQL 프롬프트)
4. 뉴스 광고 필터 + 180일 노후 필터
5. 환각 방지 (오늘 날짜 주입 + 환각 금지 프롬프트)
6. LLM 모델 계층화 (`LLM_MODEL_SYNTHESIS`)
7. 두 DB 성격 구분 + 네이버 DB 적극 활용 유도
8. 사람 친화적 표현 (금액 단위·면적·한국어 컬럼명)
9. SQL 오류 대응 강화 (재시도·오류 전파·상위 모델)

---

## 1. SQL agent — LangGraph subgraph 재설계

### 배경

기존 `create_sql_agent()`는 `SQLDatabaseToolkit` + `create_agent` 기반. LLM이 `list_tables → get_schema → generate → run` 여러 tool 루프를 돌았다. 결과는 **자연어 요약**. 차트/지도 노드가 이 요약에서 위경도 같은 수치를 다시 추출하려니 누락 빈발.

### 설계

[LangChain 공식 SQL agent 패턴](https://docs.langchain.com/oss/python/langgraph/sql-agent.md)을 참고하되, 우리 DB 스키마가 **6 테이블로 고정**이라 `list_tables`/`get_schema` 단계는 프롬프트 내장으로 흡수 — 6노드 → **3노드 + 재시도 루프**로 간소화.

```
START → generate_query → check_query → run_query
              ↑  (error & attempts < 5) ←─┘
```

| 노드 | 역할 |
|------|------|
| generate_query | 자연어 → SQL (스키마·규칙 내장, error가 있으면 피드백 반영) |
| check_query | LLM이 SQL 일반 실수 재검증 |
| run_query | SELECT/WITH 가드 후 `pd.read_sql`, 에러 시 error 필드 |

State:
```python
class SqlAgentState(TypedDict):
    question: str
    sql: str | None
    rows: list[dict] | None
    error: str | None
    attempts: int
    messages: Annotated[list[AnyMessage], add_messages]
```

### Supervisor 연결

`graph.py`의 `sql_node`는 얇은 래퍼로:

```python
def sql_node(state):
    subgraph = create_sql_subgraph()
    result = subgraph.invoke({"question": state["sql_query"], "attempts": 0, ...})
    rows = result.get("rows") or []
    source = _detect_sql_source(result.get("sql", ""))  # rt_ vs nv_ 판정
    return {
        "sql_result": f"[출처: {source}]\n\n{_rows_to_markdown(rows)}",
        "sql_rows": rows,  # chart_node가 JSON으로 받음
    }
```

`SupervisorState`에 `sql_rows: list[dict]` 신규 — **chart_node가 원본 구조 그대로 사용**.

### 교훈

- 공식 패턴을 그대로 가져올 필요 없다. 우리 도메인에서 **진짜 필요한 단계만** 남긴다.
- 에이전트 출력은 자연어가 아니라 **구조화 데이터**여야 후속 노드가 활용한다.

---

## 2. chart_node + Plotly 통일

### 배경

`chart_tools.py`에 `generate_chart` 도구가 있었지만 어느 노드도 호출하지 않는 **dead code**. 설계 의도(SQL agent가 차트 생성)를 바꿔 **graph 레벨의 별도 노드**로 분리.

### 설계

```
query_generator → sql_node → chart_node → synthesize
                ↓ rag_node ────────────↑
                ↓ news_node ───────────↑
```

`chart_node` 는 `sql_rows`를 받아 **시각화 가치 판정 + tool 선택**:

| 도구 | 사용 상황 | 렌더링 |
|------|----------|--------|
| `generate_chart` | 시계열·카테고리 비교 (line/bar) | `cl.Plotly` |
| `generate_choropleth` | 수도권 시군구 히트맵 (`data/maps/metro_sgg.geojson`) | `cl.Plotly` |
| `generate_map` | 단지 마커 + 자동 클러스터(30개 이상) | `cl.Plotly` |

프리필터: `sql_query`/`sql_rows` 에 시각화 키워드(`추이`, `별`, `분포` 등)가 없으면 LLM 호출 없이 skip.

### folium → Plotly 전환 (시행착오)

처음엔 folium으로 지도를 그렸다. 하지만 Chainlit의 `.chainlit/config.toml`이 `unsafe_allow_html = false`라 folium HTML을 메시지에 직접 렌더링 불가. 선택지:

| 옵션 | 결정 |
|------|------|
| A. `unsafe_allow_html=true` + iframe | XSS 위험 소폭, 복잡 |
| B. HTML 파일 저장 + 다운로드 링크 | 인터랙티브 X |
| **C. Plotly Scattermapbox로 대체** | ✅ 채택 — 의존성 하나 제거, 렌더 확실 |

### 교훈

- 프레임워크의 **제약 조건**은 설계 결정 전에 확인하라. 기능이 풍부한 것보다 **지금 운영 스택에 맞는 것**이 우위.

---

## 3. 위치/가격 질문 필수 컬럼 강제

### 배경

"상위 10개 단지와 위치"에 지도가 안 나온 근본 원인: SQL이 `apt_name, road_address`만 SELECT. 위경도 없음.

### 해결

`sql_agent.py` `GENERATE_PROMPT`에 규칙 명시:

```
## SELECT 컬럼 규칙 (필수)
1. 위치·단지 질문: apt_name, admin_dong, latitude, longitude 반드시 포함
2. 가격 질문: 위 + exclusive_area 반드시 포함
3. 시계열: deal_date + 집계값
```

이로써 `sql_rows`에 lat/lon이 항상 포함 → `chart_node`가 `generate_map`을 호출할 수 있다.

---

## 4. 뉴스 광고·노후 기사 필터

### 배경

"최근 부동산 뉴스"를 물으니 광고성 분양 글 또는 6개월 이상 지난 기사가 주로 나왔다.

### 해결

`news_agent.py` 에 3단 필터:

```python
# 1. 광고 패턴 (제목·description·URL)
_AD_BRACKET_RE = re.compile(r"\[\s*(광고|AD|PR|보도자료|분양특집|특집|스폰서|Sponsored|기획)\s*\]", re.IGNORECASE)
_AD_TITLE_KEYWORDS = ("모델하우스", "선착순 분양", "특별 분양", "마감임박", "즉시입주", ...)
_AD_URL_PATTERNS = ("/ad/", "/promo/", "/pr/", "advertise", "sponsored", "promotion")

# 2. RFC822 pubDate 파싱 → 180일 초과 제외
def _parse_pubdate(pub_date: str) -> datetime | None:
    return parsedate_to_datetime(pub_date).astimezone(_KST)

# 3. API 요청 5→30, 상위 3→10 반환
```

## 5. 환각 방지

### 문제 사례

답변에 "2024년 11월 기준 강남구 13.6% 상승 (PDF)" — **실제로는 PDF에 그런 수치 없음**. LLM의 자기 지식 삽입.

### 해결

`synthesize` 프롬프트에 강화 규칙:

```
오늘 날짜: {today_str}.

## 규칙
- 에이전트 결과 안의 사실만 인용. 결과에 없는 통계·사건·수치·날짜를 절대 만들지 마세요.
- 뉴스 기사 날짜가 오늘보다 과거이면 'YYYY-MM-DD 보도' 형태로 시점 명시.
- 과거 기사를 현재형으로 쓰지 마세요.
```

`news_agent`에도 동일한 "오늘 날짜" 프롬프트 주입.

### 교훈

- Gemini Flash-Lite 같은 작은 모델은 자기 학습지식을 **무의식적으로 끌어온다**. 명시적 "만들지 마라" 지시가 반드시 필요.

---

## 6. LLM 모델 계층화

### 배경

Flash-Lite가 **지시 준수**(JSON 형식 유지, 맥락 유지, 표 보존)가 약하다. 전역 상위 모델 교체는 비용 부담. **단계별 분리**가 해법.

### 설계

```python
# shared/config.py
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
LLM_MODEL_SYNTHESIS: str = os.getenv("LLM_MODEL_SYNTHESIS", LLM_MODEL)

# agents/config.py
def get_llm(model: str | None = None) -> BaseChatModel:
    return ChatGoogleGenerativeAI(model=model or LLM_MODEL)
```

| 단계 | 모델 |
|------|------|
| `query_generator` (rewrite+라우팅) | **LLM_MODEL_SYNTHESIS** (`gemini-3.1-flash`) |
| `sql_agent.generate_query` | LLM_MODEL_SYNTHESIS (SQL 구문 정확성) |
| `sql_agent.check_query` | LLM_MODEL_SYNTHESIS |
| `synthesize` | LLM_MODEL_SYNTHESIS (다중 소스 종합) |
| `chart_node` 판정 | LLM_MODEL (간단) |
| `rag_agent` / `news_agent` | LLM_MODEL |

운영 시 `.env`에서 언제든 교체 가능하도록 환경변수 기반.

### 교훈

- **모델 전부를 한 단계로 끌 필요 없다.** 지시 준수가 중요한 지점만 업그레이드.
- 환경변수로 분리하면 실험과 롤백이 쉽다.

---

## 7. 국토부 vs 네이버 DB 구분

### 배경

"정책이 아파트 매물에 미치는 영향" 질문에 SQL이 `rt_trade`만 조회. 정책·매물 질문은 **네이버 호가 DB**가 더 선행 지표인데도 미활용. LLM이 네이버 매물 DB 개념을 학습하지 못한 탓.

### 해결 — 3단계 강화

**a. SQL agent 프롬프트에 두 DB 성격 섹션**

```
🅰 국토부 실거래가 (rt_*) — 과거·확정 / 후행 지표
🅱 네이버 매물 (nv_*) — 현재 호가·공급 / 선행 지표

## 어떤 DB를 선택할지
| 질문 키워드 | 주 DB |
|---|---|
| "거래", "실거래", "매매가" | rt_trade / rt_rent |
| "매물", "호가", "공급", "시장 분위기" | nv_listing |
| "정책·이슈 영향" | nv_listing 우선 |
| "실거래가 vs 호가 괴리" | 두 DB 조인 (complex_mapping) |
```

**b. query_generator 프롬프트: `sql_query`에 어느 DB인지 명시 강제**

```
sql_query: "국토부 rt_trade 기준 ...", "네이버 nv_listing 기준 ..."
```

**c. sql_node 자동 출처 판정**

```python
def _detect_sql_source(sql: str) -> str:
    uses_rt = any(t in sql.lower() for t in ("rt_trade", "rt_rent", "rt_complex"))
    uses_nv = any(t in sql.lower() for t in ("nv_listing", "nv_complex"))
    if uses_rt and uses_nv: return "국토부 실거래가 + 네이버 매물"
    if uses_rt: return "국토부 실거래가"
    if uses_nv: return "네이버 매물"
    return "DB"

# sql_result = f"[출처: {source}]\n\n{table}"
```

**d. synthesize 프롬프트에 출처 태그 활용 지시**

```
(국토부 실거래가) / (네이버 매물) / (국토부 + 네이버) 로 표기
두 DB가 함께 조회되면 "실거래가는 X 반면 현재 호가는 Y" 대비 설명
```

### 교훈

- LLM의 학습 지식에 없는 **도메인 특화 DB**는 프롬프트로 성격·용도·사용 예시까지 가르쳐야 한다. "존재한다"만으론 부족.
- 코드가 자동 추론할 수 있는 메타정보(출처 등)는 **코드로** 태깅해 LLM에게 넘긴다.

---

## 8. 사람 친화적 표현

### 배경

답변 표에 `1376800.0`, `37.5260635520221`, `apt_name` 같은 원시값·SQL 컬럼명 그대로 노출. 사용자가 읽기 어렵다.

### 시행착오

**1차 시도**: `_format_cell` 함수로 코드 하드코딩 포맷. 컬럼명 패턴으로 가격/좌표/면적 자동 변환.

**사용자 피드백**: "synthesize LLM에게 친화 표현 시스템 프롬프트로 지시하는 게 포괄적이고 효과적" → 코드 롤백.

**2차**: synthesize 프롬프트에 규칙 내재화:

```
## 사람 친화적 표현
- 금액(만원 단위): 1억 이상은 '137.68억', 미만은 '5,000만원'. 원본 1,376,800 → '137.68억'.
- 면적(㎡): 소수 1자리 + 평 환산 병기. 84.50㎡ (25.7평). 1평=3.3058㎡.
- 좌표·apt_id 같은 내부 식별자: 본문 표에서 제외.
- 원본 수치의 의미는 바꾸지 말고 표현만.

## 표 컬럼명 한국어 변환 (필수)
- apt_name / complex_name → 단지명
- current_price → 현재 호가,  deal_amount → 거래액
- exclusive_area → 전용면적
- avg_X → '평균 X', max_X → '최고 X', ...
```

### 교훈

- **프롬프트 vs 코드**: 코드 하드코딩은 확정적이지만 패턴마다 분기 필요. 프롬프트는 유연하지만 모델 능력 필요. **상위 모델을 쓰는 단계라면 프롬프트가 낫다** (이번 경우).
- 사람 친화 변환을 코드로 박아두면 "새 컬럼이 추가될 때마다 코드 고쳐야" 하는 유지 부담.

---

## 9. SQL 오류 대응 강화

### 증상

"실거래가 vs 호가 괴리율" 같은 CTE + JOIN 복합 쿼리가 3회 재시도 후에도 실패.

### 3종 대응

```python
# 1. 상위 모델로 SQL 생성 (구문 정확성)
def generate_query(state):
    llm = get_llm(LLM_MODEL_SYNTHESIS)
    ...

# 2. 재시도 3 → 5
_MAX_ATTEMPTS = 5

# 3. 오류 메시지 500자 → 2000자 (재생성 LLM이 원인 파악)
return {"error": str(e)[:2000], ...}
```

그리고 query_generator 프롬프트:

```
sql_query는 하나의 SELECT로 실행 가능한 수준으로 유지.
과도한 CTE 여러 개·복잡한 다중 JOIN을 '한 쿼리로 전부'로 지시하지 마세요.
```

### 교훈

- 에러 메시지를 잘라 LLM에 주면 재생성이 **헛스윙**만 한다. 충분히 상세한 context 전파가 중요.
- 애초에 LLM이 감당 못할 복잡한 쿼리를 요구하지 않는 것이 근본.

---

## 10. Remote → Local DB 동기화 (부가)

개발 중 Local DB가 Remote에 비해 2주 이상 뒤처졌다. 검증 일관성을 위해 한 번 동기화.

```bash
ssh deepdata "docker exec <aptdb> pg_dump -U postgres -d apt_insight -Fc -f /tmp/sync.dump"
docker cp <aptdb>:/tmp/sync.dump /data/aptinsight/data/backups/
scp deepdata:/data/aptinsight/data/backups/backup_remote_YYYYMMDD.dump data/backups/
pg_restore -h localhost -U postgres -d apt_insight --clean --if-exists --no-owner --no-privileges data/backups/backup_remote_YYYYMMDD.dump
```

Dokploy 볼륨(`/data/aptinsight/data`)을 경유하므로 SCP도 같은 경로에서.

---

## 최종 에이전트 구조

```
┌──────────────────────────────────────────────────────────────┐
│  Supervisor (InMemorySaver + thread_id per session)          │
│                                                              │
│  START → query_generator (LLM_MODEL_SYNTHESIS)               │
│            │  (내부: _rewrite_to_standalone → sub-query)     │
│            ├─→ sql_node → chart_node ──┐                     │
│            ├─→ rag_node ───────────────┤                     │
│            ├─→ news_node ──────────────┤                     │
│            └─→ synthesize (LLM_MODEL_SYNTHESIS) → END        │
└──────────────────────────────────────────────────────────────┘

sql_node (SubGraph):
  START → generate_query (LLM_MODEL_SYNTHESIS)
            ↓
          check_query (LLM_MODEL_SYNTHESIS)
            ↓
          run_query ──→ (error, attempts<5) → generate_query
            ↓
          END → sql_node 래퍼가 markdown 표 + 출처 태그 + rows 반환

chart_node:
  프리필터 키워드 매칭 → LLM + 3 tools (generate_chart/choropleth/map)
  → Plotly Figure JSON 반환 → cl.Plotly로 렌더
```

---

## 핵심 교훈 (교재 독자에게)

1. **공식 패턴은 출발점이지 종점이 아니다.** 도메인 특성에 맞게 단계를 뺄 수 있으면 빼라 (SQL agent 6→3노드).
2. **에이전트의 출력은 구조화 데이터로.** 자연어는 인간용, 에이전트 간은 JSON/표가 낫다.
3. **LLM 모델은 계층화하라.** 전체 업그레이드 대신 "지시 준수가 중요한 노드만" 상위.
4. **도메인 특화 DB는 프롬프트로 교육하라.** 성격·용도·사용 예시까지. 이름만 알려주면 학습 편향에 밀린다.
5. **환각 방지는 세 층이 함께**: (a) 오늘 날짜 주입, (b) "결과 밖 사실 생성 금지", (c) 과거 기사는 시점 명시.
6. **렌더링 제약은 설계 전에 확인.** Chainlit의 `unsafe_allow_html=false` 하나가 folium 선택을 뒤집는다.
7. **프롬프트 vs 코드**: 간단한 규칙은 코드, 복합적 표현 변환은 상위 모델 + 프롬프트가 유연.
8. **오류 메시지는 잘라내지 말자.** 재생성 LLM도 원인을 알아야 고친다.
9. **시행착오도 기록하라.** rewrite_query를 별도 노드로 만들었다가 함수 내부로 통합, folium 도입→Plotly 전환, 코드 포맷→프롬프트 포맷. 이 전환 과정이 교재의 살이 된다.
10. **코드와 LLM은 서로 보완한다.** `_detect_sql_source`는 코드가 1초에 끝낼 일, LLM이 하면 시간·비용·오류. 반대로 한국어 컬럼명 변환은 LLM이 유연.

---

## 알려진 한계 / 다음 과제

- **복잡한 다중 쿼리 필요 질문**: 한 SQL로 해결 안 되는 질문(예: "지난 3개월 동안 매물이 줄어든 상위 10개 단지")은 현재도 일부 실패. sql_agent를 multi-query 모드로 확장 가능 (현재 단일 쿼리).
- **상위 모델 비용**: `LLM_MODEL_SYNTHESIS`를 Pro로 올리면 답변 품질은 더 좋아지지만 비용 2~3배. 운영 로그로 비용/품질 실측 필요.
- **레벨 B 메모리 (영속)**: 현재 InMemorySaver — 브라우저 탭 수명만. PostgresSaver + on_chat_resume 도입하면 하루 뒤 이어 대화 가능.
- **지도 인터랙션 확장**: 현재 Plotly Scattermapbox는 마커·hover만. 폴리라인(이동 경로)·히트맵 조합이 필요하면 custom Plotly 레이어 추가.

---

## 변경 파일 목록 (이번 Phase)

- `agents/sql_agent.py` — LangGraph subgraph로 전면 재작성
- `agents/graph.py` — chart_node·출처 태그·synthesize 프롬프트 대폭 강화
- `agents/chart_tools.py` — 유지 (generate_chart)
- `agents/map_tools.py` — 신규 (generate_choropleth + generate_map, Plotly 기반)
- `agents/news_agent.py` — 광고·노후 필터, 날짜 주입
- `agents/config.py` — `get_llm(model)` 시그니처 추가
- `shared/config.py` — `LLM_MODEL_SYNTHESIS` env 추가
- `app.py` — chart_data 렌더링(Plotly 통일)
- `data/maps/metro_sgg.geojson` — 수도권 시군구 경계 (신규 자원, 673KB)
- `Dockerfile` — `COPY data/maps/ ./assets/maps/` 추가 (볼륨 마운트 충돌 회피)
- `pyproject.toml` — folium 추가 후 제거 (Plotly로 통일)
