"""SQL 에이전트 — LangGraph subgraph.

자연어 질문을 PostgreSQL SELECT로 변환·실행하여 **구조화된 rows**를 반환한다.
상위 Supervisor의 `sql_node` 래퍼가 이 서브그래프를 호출한다.

Flow: generate_query → check_query → run_query
       ↑  (error & attempts < 3) ←─┘

- DB 스키마가 6 테이블로 고정이라 `list_tables` / `get_schema` 단계는 생략하고
  프롬프트에 내장 (공식 패턴 대비 간소화).
- 자연어 답변 단계는 생략 — rows 만 반환하고 Supervisor의 synthesize가 종합.
"""

import re
from datetime import date
from typing import Annotated

import pandas as pd
import sqlalchemy
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agents.config import get_llm
from shared.config import DATABASE_URL, LLM_MODEL_SYNTHESIS


# ─────────────────────────────────────────────────────────────
# 스키마 + 날짜 범위 (모듈 import 시점 1회)
# ─────────────────────────────────────────────────────────────

def _fetch_date_range() -> tuple[str, str]:
    engine = sqlalchemy.create_engine(DATABASE_URL)
    with engine.connect() as conn:
        row = conn.execute(sqlalchemy.text("""
            SELECT MIN(d), MAX(d) FROM (
                SELECT deal_date AS d FROM rt_trade
                UNION ALL
                SELECT deal_date AS d FROM rt_rent
            ) t
        """)).fetchone()
    start = row[0].strftime("%Y-%m") if row and row[0] else "N/A"
    end = row[1].strftime("%Y-%m") if row and row[1] else "N/A"
    return start, end


_START, _END = _fetch_date_range()
_TODAY = date.today().strftime("%Y년 %m월 %d일")


GENERATE_PROMPT = f"""당신은 PostgreSQL 전문가입니다. 자연어 질문을 PostgreSQL SELECT 쿼리 하나로 변환하세요.
오늘: {_TODAY}. DB 데이터는 실제이며 신뢰 가능.

## 두 종류의 데이터 성격 (매우 중요 — 질문 의도에 맞게 선택)

### 🅰 국토부 실거래가 (rt_* 접두사) — **과거·확정 거래 / 후행 지표**
- rt_trade: 계약 **완료된** 매매. 신고 의무 기반. 확정 가격.
- rt_rent: 계약 완료된 전월세.
- deal_date: 계약일 (후행. 보통 최근 데이터는 1~2주 시차).
- **용도**: 시세 추이, 거래량, 확정 가격, 동향 분석의 "결과".

### 🅱 네이버 매물 (nv_* 접두사) — **현재 호가·시장 의사 / 선행 지표**
- nv_listing: **지금 시장에 올라와 있는 매물**. 아직 거래되지 않은 호가.
  - trade_type: A1=매매, B1=전세, B2=월세
  - is_active=TRUE: 오늘 기준 노출 중인 매물 (현재 공급량)
  - is_active=FALSE: 내려간 매물 (거래 완료·철회 포함)
  - first_seen_date: 첫 등장일, last_seen_date: 마지막 확인일
  - initial_price: 최초 호가 (불변), current_price: 현재 호가
- nv_complex: 단지별 위경도·행정동.
- **용도**: 현재 호가, 매물 공급량, 정책·이슈의 **즉각적** 반영, 가격 변동 추이, 시장 분위기.

### 🔗 두 DB 연결 (rt ↔ nv)
- complex_mapping(apt_id ↔ naver_complex_no=complex_no) 로 조인 가능.
- "실거래가 vs 호가 괴리" 같은 비교 질문에 활용.

## 어떤 DB를 선택할지 (기본 규칙)

| 질문 키워드 | 주 DB |
|---|---|
| "거래", "실거래", "매매가", "전세가", "체결", "계약" | rt_trade / rt_rent |
| "매물", "호가", "공급", "나와있는", "올라온", "시장 분위기" | nv_listing |
| "현재", "지금" + 가격 | nv_listing (current_price, is_active=TRUE) |
| "정책·이슈가 시장에 미친 영향" | nv_listing 우선 (선행 반영). 여유 있으면 rt_trade 비교 |
| "상승률 / 하락률 / 추이" | 질문 맥락에 따라. 단기는 nv_listing, 장기·연간은 rt_trade |

## Tables (스키마)

- rt_complex: apt_id(PK), apt_name, build_year, road_address, jibun_address, latitude, longitude, admin_dong, sido_name, sgg_name
- rt_trade: id(PK), apt_id(FK→rt_complex), apartment_name, deal_date, deal_amount(만원), exclusive_area(㎡), floor, buyer_type, seller_type, dealing_type, cancellation_deal_type, cancellation_deal_day, registration_date
- rt_rent: id(PK), apt_id(FK→rt_complex), apartment_name, deal_date, deposit(만원), monthly_rent(만원, 0=전세), exclusive_area(㎡), floor, contract_term, contract_type
- nv_complex: complex_no(PK), complex_name, sido_name, sgg_name, dong_name, latitude, longitude
- nv_listing: article_no(PK), complex_no(FK→nv_complex), trade_type(A1=매매/B1=전세/B2=월세), exclusive_area(㎡), initial_price, current_price, rent_price, floor_info, direction, confirm_date, first_seen_date, last_seen_date, is_active
- complex_mapping: apt_id(FK→rt_complex), naver_complex_no(FK→nv_complex.complex_no)

## Joins
- rt_trade/rt_rent → rt_complex: ON apt_id
- nv_listing → nv_complex: ON complex_no
- rt_complex ↔ nv_complex: complex_mapping(apt_id → naver_complex_no=complex_no)

## Enum
- nv_listing.trade_type: A1(매매), B1(전세), B2(월세)
- rt_trade.buyer_type: 개인, 법인, 외국인, 기타
- rt_trade.dealing_type: 중개거래, 직거래
- rt_rent.contract_type: 신규, 갱신
- nv_complex.sido_name: 서울특별시, 경기도, 인천광역시

## SELECT 컬럼 규칙 (필수)

1. **위치·단지 관련 질문** (어느 단지, 어디, 위치, 지도 등):
   SELECT에 반드시 다음을 포함하세요.
   - apt_name(또는 complex_name), admin_dong(또는 dong_name), latitude, longitude
   - 가능하면 sgg_name / sido_name 도 함께

2. **가격 관련 질문** (평균·최고·거래가·매매·전세·월세·시세 등):
   위 컬럼 + exclusive_area(㎡) 필수 포함. 집계 시에는 GROUP BY에도 맞추세요.

3. **시계열/추이** (월별·일별·기간별):
   deal_date 또는 DATE_TRUNC('month', deal_date) + 집계값.

## 동(洞) 필터 — 법정동/행정동 괴리 흡수 (중요)

사용자는 보통 **법정동**('망원동','역삼동')으로 말하지만 DB 의 `admin_dong`/`dong_name` 은
**행정동**('망원1동','망원2동','역삼1동')으로 쪼개져 있다. 동 이름 필터는 반드시 아래
패턴으로 작성해 둘 다 커버할 것.

- **rt_* 테이블** (rt_complex.admin_dong + rt_complex.jibun_address 활용):
  `(rt_complex.admin_dong LIKE '<동>%' OR rt_complex.jibun_address LIKE '<동>%')`
  - `jibun_address` 는 '<법정동> <지번>' 형식이라 법정동명으로 시작.
- **nv_* 테이블** (nv_complex.dong_name 만 존재):
  `nv_complex.dong_name LIKE '<동>%'`
  - 대부분의 법정동은 행정동 이름의 접두사 ('망원동'→'망원1동'). 접두사가 다른 소수
    예외('신수동'→'용강동')는 이 쿼리에서 놓치지만, 일반적 질의는 이 패턴으로 충분.
- 사용자가 명시적으로 행정동 전체명('망원1동')을 말하면 그 문자열 그대로 `LIKE '망원1동%'`.

## 기타

- SELECT 또는 WITH ... SELECT 만 허용. INSERT/UPDATE/DELETE 금지.
- LIMIT 10 기본. 시계열·집계는 LIMIT 생략 가능.
- rt_trade/rt_rent.deal_date 범위: {_START} ~ {_END}. 범위 밖은 빈 결과.
- 평→㎡: 1평 = 3.3058㎡. 예: 34평 ≈ 112.40㎡.
- sgg_name 예: '강남구', '수원시 장안구'. rt_complex 와 nv_complex 양쪽에 존재하므로 시·구 필터는 **추가 JOIN 없이** 해당 테이블의 sgg_name 에 직접 `WHERE` 걸기.
- 변동률: LAG(deal_amount) OVER (PARTITION BY apt_id, exclusive_area ORDER BY deal_date)
- 환산보증금: deposit + monthly_rent * 12 / 0.045

## 출력 형식

SQL 쿼리 **하나만** 코드 블록으로:

```sql
SELECT ...
```

설명·주석·다른 텍스트 금지.
"""


CHECK_PROMPT = """다음 PostgreSQL 쿼리의 일반적 실수를 점검하세요.

점검 항목:
- NOT IN with NULL
- UNION vs UNION ALL
- BETWEEN 경계
- 동일 데이터에 부적절한 조인
- DISTINCT / GROUP BY 누락 또는 오용
- 함수 인자 수·타입
- 필요한 캐스팅 누락
- JOIN 조건 누락
- SELECT 컬럼 규칙 준수 (위치·가격 질의 시 latitude/longitude/exclusive_area 누락 여부)

출력 규칙:
- 수정 필요 → 수정된 SQL을 ```sql ... ``` 블록으로 반환
- 수정 불필요 → 원본 SQL을 그대로 같은 형식으로 반환
- 설명·주석 금지
"""


# ─────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────

class SqlAgentState(TypedDict):
    question: str
    sql: str | None
    rows: list[dict] | None
    error: str | None
    attempts: int
    messages: Annotated[list[AnyMessage], add_messages]


_SQL_RE = re.compile(r"```sql\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _extract_sql(raw) -> str:
    if isinstance(raw, list):
        raw = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in raw)
    raw = raw or ""
    m = _SQL_RE.search(raw)
    sql = (m.group(1) if m else raw).strip().rstrip(";").strip()
    return sql


def _is_safe_select(sql: str) -> bool:
    head = sql.lstrip().lower()
    return head.startswith("select") or head.startswith("with")


# ─────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────

def generate_query(state: SqlAgentState) -> dict:
    """자연어 질문 → SQL. 이전 error가 있으면 피드백 반영.

    구문 정확성이 중요하므로 상위 모델(LLM_MODEL_SYNTHESIS) 사용.
    """
    llm = get_llm(LLM_MODEL_SYNTHESIS)
    msgs = [
        SystemMessage(content=GENERATE_PROMPT),
        HumanMessage(content=state["question"]),
    ]
    if state.get("error") and state.get("sql"):
        msgs.append(HumanMessage(content=(
            f"이전 쿼리 실행 오류:\n{state['error']}\n\n"
            f"이전 SQL:\n```sql\n{state['sql']}\n```\n"
            f"오류를 고친 SQL을 다시 작성하세요."
        )))
    response = llm.invoke(msgs)
    sql = _extract_sql(response.content)
    return {
        "sql": sql,
        "attempts": state.get("attempts", 0) + 1,
        "error": None,
        "messages": [AIMessage(content=f"[generate_query] {sql[:200]}")],
    }


def check_query(state: SqlAgentState) -> dict:
    """SQL 일반적 실수 점검. 구문 판정이라 상위 모델 사용."""
    sql = state.get("sql") or ""
    if not sql:
        return {}
    llm = get_llm(LLM_MODEL_SYNTHESIS)
    response = llm.invoke([
        SystemMessage(content=CHECK_PROMPT),
        HumanMessage(content=f"```sql\n{sql}\n```"),
    ])
    checked = _extract_sql(response.content) or sql
    return {
        "sql": checked,
        "messages": [AIMessage(content=f"[check_query] {checked[:200]}")],
    }


def run_query(state: SqlAgentState) -> dict:
    """SQL 실행. SELECT/WITH 만 허용. 실패 시 error 저장."""
    sql = state.get("sql") or ""
    if not _is_safe_select(sql):
        return {"error": "SELECT/WITH 이외의 쿼리는 허용되지 않습니다."}

    try:
        engine = sqlalchemy.create_engine(DATABASE_URL)
        df = pd.read_sql(sqlalchemy.text(sql), engine)
        rows = df.to_dict(orient="records")
        return {
            "rows": rows,
            "error": None,
            "messages": [AIMessage(content=f"[run_query] {len(rows)} rows")],
        }
    except Exception as e:
        # 재생성 LLM이 원인을 파악할 수 있도록 충분히 상세한 오류 전파
        return {
            "error": str(e)[:2000],
            "messages": [AIMessage(content=f"[run_query error] {str(e)[:300]}")],
        }


_MAX_ATTEMPTS = 5


def _should_retry(state: SqlAgentState) -> str:
    if state.get("error") and state.get("attempts", 0) < _MAX_ATTEMPTS:
        return "generate_query"
    return END


# ─────────────────────────────────────────────────────────────
# Subgraph
# ─────────────────────────────────────────────────────────────

def create_sql_subgraph():
    """SQL 에이전트 서브그래프를 컴파일하여 반환."""
    builder = StateGraph(SqlAgentState)
    builder.add_node("generate_query", generate_query)
    builder.add_node("check_query", check_query)
    builder.add_node("run_query", run_query)

    builder.add_edge(START, "generate_query")
    builder.add_edge("generate_query", "check_query")
    builder.add_edge("check_query", "run_query")
    builder.add_conditional_edges("run_query", _should_retry, ["generate_query", END])

    return builder.compile()
