"""Supervisor StateGraph — 서브에이전트 오케스트레이션.

query_generator → [sql_node + news_node + rag_node] (병렬) → synthesize → END

query_generator가 사용자 질문을 분석하여 각 에이전트에 맞는 질의를 생성한다.
가급적 3개 에이전트 모두에게 질의를 생성하여 종합적인 답변을 제공한다.
"""

import json
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agents.config import get_llm
from agents.news_agent import create_news_agent
from agents.rag_agent import create_rag_agent
from agents.sql_agent import create_sql_agent


# ==============================================================================
# State
# ==============================================================================

class SupervisorState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    sql_query: str | None        # SQL 에이전트에 전달할 질의
    rag_query: str | None        # RAG 에이전트에 전달할 질의
    news_query: str | None       # News 에이전트에 전달할 질의
    sql_result: str | None
    rag_result: str | None
    news_result: str | None
    chart_data: str | None       # Plotly JSON


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

REWRITE_PROMPT = (
    "이전 대화를 반영해 마지막 사용자 질문을 혼자서도 이해 가능한 "
    "완전한 한국어 문장 한 줄로 재작성하세요. "
    "지시대명사·생략된 지역/기간/거래유형을 이전 대화의 구체 값으로 채우되, "
    "새 주제(다른 지역명 등)가 명시되면 이전 맥락은 버리세요. "
    "인사나 짧은 잡담은 그대로 반환하세요. "
    "오직 질문 한 줄만 출력. 설명·따옴표·prefix 금지."
)


QUERY_GENERATOR_PROMPT = """당신은 부동산 질문 분석가입니다. 사용자 질문을 분석하여 3개 에이전트 각각에 적합한 질의를 생성하세요.

## 에이전트 역할

1. **sql_agent** — DB에서 아파트 실거래가·전월세·매물 수치 데이터를 조회합니다.
2. **news_agent** — 네이버 검색 API로 최신 부동산 뉴스를 실시간 검색합니다.
3. **rag_agent** — 사용자가 업로드한 PDF 문서에서 관련 내용을 검색합니다.

## 출력 형식

반드시 아래 JSON 형식으로만 답하세요.

```json
{
  "sql_query": "SQL 에이전트에게 보낼 질의 (불필요하면 null)",
  "news_query": "News 에이전트에게 보낼 질의 (불필요하면 null)",
  "rag_query": "RAG 에이전트에게 보낼 질의 (불필요하면 null)"
}
```

## 규칙

- 가급적 3개 모두 질의를 생성해 종합적 답변이 가능하게 하되, 맥락상 불필요하면 null.
- 단순 인사(안녕하세요, 뭘 할 수 있어?)는 3개 모두 null.
- 입력에 지역명이 있으면 그 지역명을 모든 질의에 유지하세요.
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


def _rewrite_to_standalone(llm, messages: list[AnyMessage]) -> str:
    """이전 대화를 반영해 마지막 사용자 질문을 standalone 질문으로 재작성.

    첫 턴이면 원문 그대로 반환. 단순 전처리이므로 query_generator 내부에서만 사용.
    """
    last_content = messages[-1].content if messages else ""
    if len(messages) <= 1:
        return last_content

    recent = messages[-8:]
    hint = HumanMessage(content=f"[마지막 질문] {last_content}")
    response = llm.invoke([SystemMessage(content=REWRITE_PROMPT), *recent[:-1], hint])
    rewritten = _extract_text(response.content).strip().strip('"').strip("'")
    return rewritten or last_content


def query_generator(state: SupervisorState) -> dict:
    """사용자 질문을 분석하여 각 에이전트에 맞는 질의를 생성한다.

    이전 대화가 있으면 먼저 standalone 질문으로 재작성한 뒤 라우팅 질의를 생성한다.
    """
    llm = get_llm()
    user_content = _rewrite_to_standalone(llm, state["messages"])

    response = llm.invoke([
        SystemMessage(content=QUERY_GENERATOR_PROMPT),
        HumanMessage(content=user_content),
    ])
    queries = _parse_json(_extract_text(response.content))

    if not queries:
        # JSON 파싱 실패 → 원본 질문으로 sql+news 호출
        return {"sql_query": user_content, "news_query": user_content}

    sql_q = queries.get("sql_query")
    news_q = queries.get("news_query")
    rag_q = queries.get("rag_query")

    # 3개 모두 null인데 단순 인사가 아닌 경우 → sql+news 강제 생성
    if not sql_q and not news_q and not rag_q:
        greetings = ("안녕", "하이", "hello", "hi", "뭘 할 수", "도움", "help")
        if not any(g in user_content.lower() for g in greetings):
            return {"sql_query": user_content, "news_query": user_content}

    return {"sql_query": sql_q, "rag_query": rag_q, "news_query": news_q}


def sql_node(state: SupervisorState) -> dict:
    """SQL 에이전트 — DB에서 아파트 실거래가·전월세·매물 수치 데이터를 조회한다."""
    query = state.get("sql_query")
    if not query:
        return {"sql_result": None}

    agent = create_sql_agent()
    result = agent.invoke(
        {"messages": [HumanMessage(content=query)]},
        {"recursion_limit": 30},
    )
    return {"sql_result": _extract_text(result["messages"][-1].content)}


def rag_node(state: SupervisorState) -> dict:
    """RAG 에이전트 — 업로드된 PDF 문서에서 관련 내용을 검색한다."""
    query = state.get("rag_query")
    if not query:
        return {"rag_result": None}

    agent = create_rag_agent()
    result = agent.invoke(
        {"messages": [HumanMessage(content=query)]},
        {"recursion_limit": 15},
    )
    return {"rag_result": _extract_text(result["messages"][-1].content)}


def news_node(state: SupervisorState) -> dict:
    """News 에이전트 — 네이버 검색 API로 최신 부동산 뉴스를 검색한다."""
    query = state.get("news_query")
    if not query:
        return {"news_result": None}

    agent = create_news_agent()
    result = agent.invoke(
        {"messages": [HumanMessage(content=query)]},
        {"recursion_limit": 15},
    )
    return {"news_result": _extract_text(result["messages"][-1].content)}


def synthesize(state: SupervisorState) -> dict:
    """서브에이전트 결과를 종합하여 출처를 명시한 최종 답변을 생성한다."""
    llm = get_llm()

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

    context = "\n\n".join(parts)
    prompt = SystemMessage(content=(
        "아래 에이전트 결과를 종합하여 사용자의 마지막 질문에 답변하세요.\n\n"
        "규칙:\n"
        "- 반드시 각 정보의 출처를 명시하세요: (DB 조회), (뉴스), (PDF 문서) 등.\n"
        "- 서브에이전트가 반환한 날짜·수치를 절대로 임의로 변경하지 마세요.\n"
        "- PDF 검색 결과가 없다는 내용은 답변에 포함하지 마세요.\n"
        "- 이전 대화의 맥락(지역, 기간, 관심사)을 자연스럽게 이어가세요.\n"
        "- 한국어로 답변하세요.\n\n"
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
    builder.add_node("rag_node", rag_node)
    builder.add_node("news_node", news_node)
    builder.add_node("synthesize", synthesize)

    builder.add_edge(START, "query_generator")
    builder.add_conditional_edges(
        "query_generator",
        _route_to_agents,
        ["sql_node", "rag_node", "news_node", "synthesize"],
    )
    builder.add_edge("sql_node", "synthesize")
    builder.add_edge("rag_node", "synthesize")
    builder.add_edge("news_node", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=checkpointer)
