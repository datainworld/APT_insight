"""Chainlit 웹 채팅 서버.

수도권 아파트 거래·시세·뉴스 멀티에이전트 시스템.
실행: chainlit run app.py
"""

import json
import os
import shutil
import uuid

import chainlit as cl
import plotly.graph_objects as go
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.checkpoint.memory import InMemorySaver

from agents.config import get_vector_store
from agents.graph import create_supervisor_graph, _extract_text

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 노드 이름 → UI 표시 레이블
_NODE_LABELS: dict[str, str] = {
    "query_generator": "> 질의 생성",
    "sql_node": "> DB 조회",
    "chart_node": "> 시각화",
    "rag_node": "> PDF 검색",
    "news_node": "> 뉴스 검색",
    "synthesize": "> 답변 종합",
}

# 에이전트 질의 키 → UI 접두사
_QUERY_LABELS: dict[str, str] = {
    "sql_query": "[SQL]",
    "news_query": "[News]",
    "rag_query": "[RAG]",
}


# ==============================================================================
# PDF 업로드 처리
# ==============================================================================

def _process_pdf_sync(file_path: str, file_name: str) -> str:
    """PDF 파일을 청킹 → 임베딩 → PGVector에 저장한다."""
    import fitz  # PyMuPDF

    dest = os.path.join(UPLOAD_DIR, file_name)
    shutil.copy(file_path, dest)

    doc = fitz.open(dest)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            pages.append({"text": text, "page": i + 1})
    doc.close()

    if not pages:
        return f"'{file_name}'에서 텍스트를 추출할 수 없습니다."

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    documents = []
    for p in pages:
        for chunk in splitter.split_text(p["text"]):
            documents.append(Document(
                page_content=chunk,
                metadata={"source": file_name, "page": p["page"]},
            ))

    vector_store = get_vector_store()
    vector_store.add_documents(documents)

    return f"**{file_name}** 업로드 완료 -- {len(pages)}페이지, {len(documents)}청크 저장. 이제 이 문서에 대해 질문할 수 있습니다."


# ==============================================================================
# Chainlit 이벤트 핸들러
# ==============================================================================

@cl.set_starters
async def set_starters() -> list[cl.Starter]:
    return [
        cl.Starter(
            label="급등/급락 아파트",
            message="최근 3개월간 매매가가 가장 많이 오른 아파트와 가장 많이 떨어진 아파트는?",
        ),
        cl.Starter(
            label="갭투자 유망 지역",
            message="매매가 대비 전세가 비율이 높아서 갭투자가 용이한 행정동은 어디인가요?",
        ),
        cl.Starter(
            label="허위매물 의심 지역",
            message="네이버 매물 중 장기간 등록되어 있거나 호가 변동이 큰 의심 매물이 많은 지역은?",
        ),
        cl.Starter(
            label="정책이 시장에 미치는 영향",
            message="최근 부동산 정책이 아파트 매매 및 전세 시장에 미치는 영향은?",
        ),
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    # 세션 수명 동안만 유지되는 멀티턴 메모리 (브라우저 새로고침·재접속 시 초기화)
    graph = create_supervisor_graph(checkpointer=InMemorySaver())
    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", str(uuid.uuid4()))


@cl.on_message
async def on_message(message: cl.Message) -> None:
    # ── 첨부 PDF 처리 (클립 아이콘 / 드래그앤드롭) ──
    if message.elements:
        for elem in message.elements:
            if hasattr(elem, "name") and elem.name.lower().endswith(".pdf"):
                status = cl.Message(content=f"'{elem.name}' 처리 중...")
                await status.send()
                result = await cl.make_async(_process_pdf_sync)(elem.path, elem.name)
                status.content = result
                await status.update()
        return

    # ── 에이전트 질의 처리 ──
    graph = cl.user_session.get("graph")
    thread_id = cl.user_session.get("thread_id")

    final_msg = cl.Message(content="")
    await final_msg.send()

    chart_data = None

    async for event in graph.astream(
        {"messages": [HumanMessage(content=message.content)]},
        {"recursion_limit": 50, "configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    ):
        for node_name, update in event.items():
            # 노드가 빈 dict 를 반환하면 LangGraph 가 None 으로 emit 하는 경우가 있음
            if update is None:
                update = {}

            # ── query_generator: 생성된 질의를 Step으로 표시 ──
            if node_name == "query_generator":
                step = cl.Step(name=_NODE_LABELS.get(node_name, node_name), type="tool")
                lines = []
                for key, label in _QUERY_LABELS.items():
                    q = update.get(key)
                    if q:
                        lines.append(f"{label} {q}")
                step.output = "\n".join(lines) if lines else "직접 답변"
                await step.send()
                await step.update()

            # ── 에이전트 노드: 완료 시 결과 표시 ──
            elif node_name in ("sql_node", "rag_node", "news_node"):
                result_key = node_name.replace("_node", "_result")
                result = update.get(result_key)

                step = cl.Step(
                    name=_NODE_LABELS.get(node_name, node_name),
                    type="tool",
                )
                if result:
                    step.output = result[:500] + "…" if len(result) > 500 else result
                else:
                    step.output = "결과 없음"
                await step.send()
                await step.update()

            # ── chart_node: 시각화 생성 여부를 Step으로 표시 ──
            elif node_name == "chart_node":
                step = cl.Step(name=_NODE_LABELS[node_name], type="tool")
                if update.get("chart_data"):
                    chart_data = update["chart_data"]
                    step.output = "차트 생성 완료"
                else:
                    step.output = "차트 불필요"
                await step.send()
                await step.update()

            # ── synthesize: 최종 답변 ──
            elif node_name == "synthesize":
                msgs = update.get("messages", [])
                if msgs:
                    text = _extract_text(msgs[-1].content)
                    if text:
                        final_msg.content = text
                        await final_msg.update()

    await final_msg.update()

    # ── 시각화 렌더링 (Plotly Figure JSON) ──
    if chart_data:
        try:
            fig = go.Figure(json.loads(chart_data))
            chart_elem = cl.Plotly(figure=fig, name="chart")
            await cl.Message(content="", elements=[chart_elem]).send()
        except Exception as e:
            print(f"[chart render error] {e}", flush=True)
