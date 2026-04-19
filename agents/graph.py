"""Supervisor StateGraph — 서브에이전트 오케스트레이션.

query_generator → [sql_node + news_node + rag_node] (병렬) → synthesize → END

query_generator가 사용자 질문을 분석하여 각 에이전트에 맞는 질의를 생성한다.
가급적 3개 에이전트 모두에게 질의를 생성하여 종합적인 답변을 제공한다.
"""

import json
from datetime import date
from typing import Annotated

from langchain.agents import create_agent
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

import pandas as pd

from agents.chart_tools import generate_chart
from agents.config import get_llm
from agents.map_tools import generate_choropleth, generate_map
from agents.news_agent import run_news
from agents.rag_agent import run_rag
from agents.sql_agent import create_sql_subgraph
from shared.config import LLM_MODEL_SYNTHESIS


# ==============================================================================
# State
# ==============================================================================

class SupervisorState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    sql_query: str | None        # SQL 에이전트에 전달할 질의
    rag_query: str | None        # RAG 에이전트에 전달할 질의
    news_query: str | None       # News 에이전트에 전달할 질의
    sql_result: str | None       # SQL 결과 markdown 표 요약 (synthesize용)
    sql_rows: list[dict] | None  # SQL 결과 구조화 rows (chart_node용)
    rag_result: str | None
    news_result: str | None
    chart_data: str | None       # Plotly Figure JSON


# ==============================================================================
# 헬퍼
# ==============================================================================

def _extract_text(content) -> str:
    """Gemini가 content를 리스트로 반환할 때 텍스트를 추출한다."""
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    return content or ""


# ==============================================================================
# 노드
# ==============================================================================

QUERY_GENERATOR_PROMPT = """당신은 부동산 질문 분석가입니다. 사용자 질문을 분석하여 3개 에이전트 각각에 적합한 질의를 생성하세요.

## 에이전트 역할

1. **sql_agent** — 프로젝트 DB 조회. 두 종류의 데이터 출처가 있음:
   - **국토부 실거래가(rt_trade/rt_rent)** — 과거·확정 매매·전월세. 후행 지표.
   - **네이버 매물(nv_listing)** — 현재 시장 호가·공급. 선행 지표. 정책·이슈가 먼저 반영.
2. **news_agent** — 네이버 검색 API로 최신 부동산 뉴스.
3. **rag_agent** — 사용자가 업로드한 PDF 문서.

## SQL 질의 작성 가이드 (어느 DB를 볼지 명시)

| 질문 유형 | sql_query 권장 |
|---|---|
| 과거 시세·거래량·확정 가격 | "국토부 rt_trade / rt_rent 기준 ..." |
| 현재 호가·매물 수·공급량 | "네이버 nv_listing 기준 ..." |
| 정책·이슈가 시장에 미친 영향 | **네이버 nv_listing 우선** (is_active·신규/종료 매물·current_price 변화). 가능하면 국토부 실거래가와 대비 |
| 실거래가 vs 호가 괴리 | "complex_mapping으로 두 DB 조인 ..." |
| 시장 분위기·매물 추이 | **네이버 nv_listing 필수** |

네이버 매물 DB는 대부분 LLM 학습에 없는 데이터이므로 **적극 활용을 지시**하세요.

## 출력 형식

```json
{
  "sql_query": "어느 DB(국토부/네이버)를 볼지 명시한 구체적 질의 (불필요하면 null)",
  "news_query": "News 에이전트에게 보낼 질의 (불필요하면 null)",
  "rag_query": "RAG 에이전트에게 보낼 질의 (불필요하면 null)"
}
```

## 예시

- "강남구 아파트 전망" →
  sql: "국토부 rt_trade 기준 강남구 최근 3개월 매매 평균가 추이 + 네이버 nv_listing 기준 현재 active 매물 수·평균 current_price"
  news: "강남 아파트 시장 전망"
  rag: "강남 아파트 시장 분석"
- "정책이 매물에 미치는 영향" →
  sql: "네이버 nv_listing 기준 최근 3개월 월별 신규·종료 매물 수 추이와 평균 current_price 변화"
  news: "부동산 정책 아파트 매물"
- "강남 상위 10개 단지" →
  sql: "국토부 rt_trade 기준 강남구 단지별 최근 6개월 평균 deal_amount 상위 10개 (apt_name·admin_dong·latitude·longitude·exclusive_area 포함)"

## 규칙

- 가급적 3개 모두 질의를 생성해 종합 답변이 가능하게 하되, 맥락상 불필요하면 null.
- sql_query는 **어느 DB(국토부/네이버)를 볼지 반드시 명시**하세요.
- **sql_query는 하나의 SELECT로 실행 가능한 수준**으로 유지하세요. 과도한 CTE 여러 개·복잡한 다중 JOIN을 "한 쿼리로 전부"로 지시하지 마세요.
  - 두 DB 비교가 필요해도 "LEFT JOIN으로 단지별 실거래가·현재 호가를 나란히 조회" 정도까지. 여러 단계가 필요하면 sql_agent가 자체적으로 나눕니다.
- 단순 인사(안녕, 뭘 할 수 있어)는 3개 모두 null.
- 입력에 지역명이 있으면 그 지역명을 모든 질의에 유지하세요.
- 이전 대화가 있으면 맥락(지역·기간·거래유형)을 반영해 자기완결적 sub-query 를 생성하되, 새 주제(다른 지역명 등)가 명시되면 이전 맥락은 버리세요.
"""


def _parse_json(raw: str) -> dict | None:
    """LLM 응답에서 JSON을 추출한다. 실패 시 None."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def query_generator(state: SupervisorState) -> dict:
    """사용자 질문을 분석하여 각 에이전트에 맞는 질의를 생성한다.

    최근 메시지 히스토리를 그대로 LLM에 넘기면 문맥 해석(대명사·생략 복원)을
    LLM이 네이티브로 처리한다. 다운스트림 에이전트가 받는 sub-query 는
    QUERY_GENERATOR_PROMPT 지시에 따라 자기완결적으로 생성된다.
    """
    llm = get_llm(LLM_MODEL_SYNTHESIS)
    recent = state["messages"][-8:]
    last_user_text = _extract_text(state["messages"][-1].content) if state["messages"] else ""

    response = llm.invoke([SystemMessage(content=QUERY_GENERATOR_PROMPT), *recent])
    queries = _parse_json(_extract_text(response.content))

    if not queries:
        # JSON 파싱 실패 → 마지막 사용자 입력 원문으로 sql+news 호출
        return {"sql_query": last_user_text, "news_query": last_user_text}

    sql_q = queries.get("sql_query")
    news_q = queries.get("news_query")
    rag_q = queries.get("rag_query")

    # 3개 모두 null인데 단순 인사가 아닌 경우 → sql+news 강제 생성
    if not sql_q and not news_q and not rag_q:
        greetings = ("안녕", "하이", "hello", "hi", "뭘 할 수", "도움", "help")
        if not any(g in last_user_text.lower() for g in greetings):
            return {"sql_query": last_user_text, "news_query": last_user_text}

    return {"sql_query": sql_q, "rag_query": rag_q, "news_query": news_q}


def _rows_to_markdown(rows: list[dict], max_rows: int = 10) -> str:
    """rows → Markdown 표 (원본 값 그대로). 사용자 친화적 포맷은 synthesize LLM이 담당."""
    if not rows:
        return "결과 없음"
    df = pd.DataFrame(rows)
    head = df.head(max_rows)
    cols = list(head.columns)
    lines = ["| " + " | ".join(cols) + " |"]
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for _, row in head.iterrows():
        vals = [("" if pd.isna(v) else str(v)) for v in row]
        lines.append("| " + " | ".join(vals) + " |")
    body = "\n".join(lines)
    if len(df) > max_rows:
        body = f"총 {len(df)}건 중 상위 {max_rows}건:\n\n{body}"
    return body


def _detect_sql_source(sql: str) -> str:
    """실행된 SQL에서 출처 DB를 판정한다."""
    s = (sql or "").lower()
    uses_rt = any(t in s for t in ("rt_trade", "rt_rent", "rt_complex"))
    uses_nv = any(t in s for t in ("nv_listing", "nv_complex"))
    if uses_rt and uses_nv:
        return "국토부 실거래가 + 네이버 매물"
    if uses_rt:
        return "국토부 실거래가"
    if uses_nv:
        return "네이버 매물"
    return "DB"


def sql_node(state: SupervisorState) -> dict:
    """SQL 서브그래프 호출 래퍼 — question → rows + markdown 요약 + 출처 태그."""
    query = state.get("sql_query")
    if not query:
        return {"sql_result": None, "sql_rows": None}

    subgraph = create_sql_subgraph()
    try:
        result = subgraph.invoke(
            {
                "question": query,
                "sql": None,
                "rows": None,
                "error": None,
                "attempts": 0,
                "messages": [],
            },
            {"recursion_limit": 15},
        )
    except Exception as e:
        return {"sql_result": f"SQL 서브그래프 오류: {e}", "sql_rows": None}

    if result.get("error"):
        return {
            "sql_result": f"SQL 실행 실패: {result['error']}",
            "sql_rows": None,
        }

    rows = result.get("rows") or []
    source = _detect_sql_source(result.get("sql", ""))
    table = _rows_to_markdown(rows)
    return {
        "sql_result": f"[출처: {source}]\n\n{table}",
        "sql_rows": rows,
    }


def rag_node(state: SupervisorState) -> dict:
    """RAG — 업로드된 PDF 문서에서 관련 내용을 검색 후 1회 LLM 호출로 요약."""
    query = state.get("rag_query")
    if not query:
        return {"rag_result": None}
    return {"rag_result": run_rag(query)}


def news_node(state: SupervisorState) -> dict:
    """News — 네이버 검색 API로 기사 수집 후 1회 LLM 호출로 요약."""
    query = state.get("news_query")
    if not query:
        return {"news_result": None}
    return {"news_result": run_news(query)}


CHART_PROMPT = """당신은 SQL 분석 결과에 적합한 시각화를 판단하는 역할입니다.
제공된 질의와 분석 결과를 검토하여, 시각화가 유용한 경우에만 **도구 하나를 1회** 호출하세요.

## 도구 선택

1. **generate_chart** — 시계열·카테고리 비교 (line/bar/scatter). 2개 이상 수치.
   - 시계열(월별/일별/연도별 추이) → chart_type=line
   - 카테고리 비교(단지별/면적별 값 2~10개) → chart_type=bar
2. **generate_choropleth** — 수도권 시군구 3개 이상의 지역별 수치 비교 (히트맵).
   - locations는 시군구 한글명. 복합 지역은 공백 없이: "수원시장안구", "성남시분당구".
3. **generate_map** — 개별 단지의 좌표(위경도)가 분석 결과에 명시될 때.
   - markers 배열에 {lat, lon, name, price} 객체. 30개 이상이면 자동 클러스터링.

## 불필요한 경우

- 단일 값 답변
- 정성적 답변
- 데이터가 2개 미만
→ 어떤 도구도 호출하지 말고 "차트 불필요"만 답하세요.

## 규칙

- 한 번만 호출합니다.
- 데이터는 분석 결과 원문에서 그대로 추출 (절대 지어내지 마세요).
- 단위는 분석 결과에 명시된 그대로 사용하세요 (만원·건 등).
"""

_CHART_TRIGGER_KEYWORDS = (
    "추이", "변화", "월별", "일별", "연도별", "상승", "하락",
    "비교", "상위", "하위", "분포", "별",
    "지역", "구별", "동별", "시군구", "지도",
    "평균", "최고", "최저",
)


def chart_node(state: SupervisorState) -> dict:
    """SQL rows에 적합한 시각화를 LLM이 선택·생성한다.

    sql_rows(구조화 데이터)를 JSON으로 LLM에 직접 전달 → lat/lon 등 정확 추출.
    프리필터로 시각화 가치가 없으면 LLM 호출 없이 skip.
    """
    rows = state.get("sql_rows")
    sql_query = state.get("sql_query") or ""
    if not rows:
        return {}

    # 프리필터: 질의 의도에 시각화 가치가 있는지
    combined = f"{sql_query}\n{str(rows[:2])[:300]}"
    if not any(kw in combined for kw in _CHART_TRIGGER_KEYWORDS):
        return {}

    # 토큰 절약: 상위 20행만 LLM에 전달
    preview = rows[:20]
    rows_json = json.dumps(preview, ensure_ascii=False, default=str)

    llm = get_llm()
    tools = [generate_chart, generate_choropleth, generate_map]
    agent = create_agent(llm, tools, system_prompt=CHART_PROMPT)

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=(
                f"[질의]\n{sql_query}\n\n"
                f"[분석 결과: {len(rows)}건 중 상위 {len(preview)}건 미리보기]\n"
                f"{rows_json}"
            ))]},
            {"recursion_limit": 5},
        )
    except Exception:
        return {}

    for msg in result["messages"]:
        if not isinstance(msg, ToolMessage):
            continue
        content = _extract_text(msg.content)
        if content:
            return {"chart_data": content}

    return {}


def synthesize(state: SupervisorState) -> dict:
    """서브에이전트 결과를 종합하여 출처를 명시한 최종 답변을 생성한다.

    다중 소스 종합·표 정확 전달이 중요한 단계라 상위 모델(LLM_MODEL_SYNTHESIS) 사용.
    """
    llm = get_llm(LLM_MODEL_SYNTHESIS)

    parts = []
    if state.get("sql_result"):
        parts.append(f"[DB 조회 결과]\n{state['sql_result']}")
    if state.get("rag_result"):
        parts.append(f"[PDF 검색 결과]\n{state['rag_result']}")
    if state.get("news_result"):
        parts.append(f"[뉴스 검색 결과]\n{state['news_result']}")

    # 최근 맥락 (이전 대화 흐름 반영용). 마지막 사용자 질문 포함.
    recent = state["messages"][-8:]

    # direct (인사/일반 대화) — 에이전트 결과 없음
    if not parts:
        greeting_prompt = SystemMessage(content=(
            "당신은 수도권 아파트 거래·시세·뉴스 분석 시스템입니다.\n"
            "사용자의 인사나 일반 질문에 간단히 답하세요.\n"
            "DB 조회, 뉴스 검색, PDF 검색 없이는 부동산 관련 구체적 수치나 뉴스를 답할 수 없습니다.\n"
            "부동산 질문이라면 다시 질문해달라고 안내하세요."
        ))
        response = llm.invoke([greeting_prompt, *recent])
        return {"messages": [AIMessage(content=_extract_text(response.content))]}

    today_str = date.today().strftime("%Y-%m-%d")
    context = "\n\n".join(parts)
    prompt = SystemMessage(content=(
        f"오늘 날짜: {today_str}.\n\n"
        "아래 에이전트 결과를 종합하여 사용자의 마지막 질문에 답변하세요.\n\n"
        "## 규칙\n"
        "- **에이전트 결과 안의 사실만** 인용하세요. 결과에 없는 통계·사건·수치·날짜를 **절대 만들지 마세요**.\n"
        "- 서브에이전트가 반환한 날짜·수치를 절대 임의로 변경하지 마세요.\n"
        f"- 뉴스 기사의 날짜가 오늘({today_str})보다 과거이면 반드시 'YYYY-MM-DD 보도' 형태로 과거 시점임을 밝히세요.\n"
        "- PDF 검색 결과가 없다는 내용은 답변에 포함하지 마세요.\n"
        "- 이전 대화의 맥락(지역, 기간, 관심사)을 자연스럽게 이어가세요.\n"
        "- 한국어로 답변하세요.\n\n"
        "## 두 부동산 DB의 성격 (이해하고 답변)\n"
        "- **국토부 실거래가(rt_*)**: 계약 완료된 과거·확정 거래. **후행 지표**. 신고 시차로 최근 1~2주 데이터는 부족할 수 있음.\n"
        "- **네이버 매물(nv_*)**: 현재 시장에 올라온 호가·매물 공급. **선행 지표**. 정책·이슈가 먼저 반영됨.\n"
        "- 두 DB는 상호 보완적이며, 같은 주제에 둘 다 인용되면 '실거래가는 X인 반면 현재 호가는 Y' 처럼 대비해 설명하세요.\n\n"
        "## 출처 표시 (중요)\n"
        "- [DB 조회] 결과는 맨 위의 '[출처: ...]' 태그를 그대로 반영하세요.\n"
        "- 국토부 실거래가 → **(국토부 실거래가)** 로 표기\n"
        "- 네이버 매물 → **(네이버 매물)** 로 표기\n"
        "- 두 DB 조합 → **(국토부 + 네이버)** 로 표기\n"
        "- 뉴스는 **(뉴스)**, PDF는 **(PDF 문서)** 로 표기.\n\n"
        "## DB 조회 표 처리\n"
        "- [DB 조회] 결과가 Markdown 표이면 **표의 수치 컬럼(평균 거래액·최고가·거래량·면적 등)을 누락 없이** 답변에 포함하세요.\n"
        "- 표 앞·뒤에 1~2문장의 자연어 해설을 덧붙여 맥락을 제공하세요.\n\n"
        "## 사람 친화적 표현\n"
        "- **금액(만원 단위)**: 1억 이상은 '137.68억', 미만은 '5,000만원'. 원본 1,376,800만원 → '137.68억'.\n"
        "- **면적(㎡)**: 소수 1자리 + 평 환산 병기. 예: 84.50㎡ (25.7평). 1평=3.3058㎡.\n"
        "- **긴 소수**: 의미 있는 자릿수까지만.\n"
        "- **좌표(latitude/longitude)·apt_id 같은 내부 식별자**: 본문 표에서 **제외**.\n"
        "- 원본 수치의 의미는 바꾸지 말고 **표현만** 친화적으로.\n\n"
        "## 표 컬럼명 한국어 변환 (필수)\n"
        "표를 답변에 포함할 때 **컬럼 제목은 반드시 한국어 라벨**로 바꾸세요. SQL 원본 컬럼명(apt_name, current_price 등) 그대로 노출 금지.\n"
        "매핑 예시:\n"
        "- apt_name / complex_name → 단지명\n"
        "- admin_dong / dong_name → 행정동\n"
        "- sgg_name → 시군구,   sido_name → 시도\n"
        "- road_address → 도로명 주소,   jibun_address → 지번 주소\n"
        "- build_year → 준공년도,   exclusive_area → 전용면적\n"
        "- floor / floor_info → 층,   direction → 향\n"
        "- deal_date → 거래일,   deal_amount → 거래액\n"
        "- deposit → 보증금,   monthly_rent → 월세,   contract_type → 계약유형\n"
        "- current_price → 현재 호가,   initial_price → 최초 호가,   rent_price → 월세(매물)\n"
        "- trade_type → 거래유형(A1 매매/B1 전세/B2 월세)\n"
        "- first_seen_date → 최초 등록일,   last_seen_date → 마지막 확인일,   is_active → 노출중\n"
        "- confirm_date → 확인일\n"
        "- avg_X → '평균 X',  max_X → '최고 X',  min_X → '최저 X',  sum_X → 'X 합계',  listing_count → 매물 수,  trade_count → 거래 수\n"
        "- 위 매핑에 없는 컬럼도 의미를 고려해 한국어로 번역하세요.\n\n"
        f"{context}"
    ))
    response = llm.invoke([prompt, *recent])
    return {"messages": [AIMessage(content=_extract_text(response.content))]}


# ==============================================================================
# 라우팅
# ==============================================================================

def _route_to_agents(state: SupervisorState) -> list[str]:
    """질의가 있는 에이전트 노드 목록을 반환한다. 병렬 실행된다."""
    targets = []
    if state.get("sql_query"):
        targets.append("sql_node")
    if state.get("news_query"):
        targets.append("news_node")
    if state.get("rag_query"):
        targets.append("rag_node")

    return targets if targets else ["synthesize"]


# ==============================================================================
# 그래프 빌더
# ==============================================================================

def create_supervisor_graph(checkpointer=None):
    """Supervisor StateGraph를 컴파일하여 반환한다.

    query_generator → [sql_node + news_node + rag_node] (병렬) → synthesize → END

    query_generator는 내부적으로 standalone 재작성(이전 대화 있을 때)을 먼저 수행한다.
    """
    builder = StateGraph(SupervisorState)

    builder.add_node("query_generator", query_generator)
    builder.add_node("sql_node", sql_node)
    builder.add_node("chart_node", chart_node)
    builder.add_node("rag_node", rag_node)
    builder.add_node("news_node", news_node)
    builder.add_node("synthesize", synthesize)

    builder.add_edge(START, "query_generator")
    builder.add_conditional_edges(
        "query_generator",
        _route_to_agents,
        ["sql_node", "rag_node", "news_node", "synthesize"],
    )
    # chart_node 는 sql_node 의 곁가지로 분리 (크리티컬 패스 제외).
    # 모든 서브에이전트가 synthesize 에 1 hop 으로 수렴해야 Pregel 이 synthesize 를
    # 단일 superstep 에서 1회만 실행한다 (이전: sql→chart→synth 2hop 로 인해 2회 실행).
    builder.add_edge("sql_node", "chart_node")
    builder.add_edge("sql_node", "synthesize")
    builder.add_edge("chart_node", END)
    builder.add_edge("rag_node", "synthesize")
    builder.add_edge("news_node", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=checkpointer)
