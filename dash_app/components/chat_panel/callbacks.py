"""기존 채팅 콜백 — Phase D 에서 4단계 패널로 재작성 예정.

지금은 import 사이드이펙트로 @callback 이 등록된다.
"""

from __future__ import annotations

import json
import re
import uuid

import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from dash_app import charts
from dash_app.components.chat_panel.layout import welcome_msg

_graph_singleton = None


def _get_graph():
    global _graph_singleton
    if _graph_singleton is None:
        from langgraph.checkpoint.memory import InMemorySaver

        from agents.graph import create_supervisor_graph

        _graph_singleton = create_supervisor_graph(checkpointer=InMemorySaver())
    return _graph_singleton


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^\s*[-*]\s+(.+)$")


def _is_table_row(line: str) -> bool:
    return bool(_TABLE_ROW_RE.match(line)) and line.strip().count("|") >= 3


def _is_table_separator(line: str) -> bool:
    if not _TABLE_SEP_RE.match(line):
        return False
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return all(c and set(c) <= set("-:") and "-" in c for c in cells)


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _inline_md(s: str) -> list:
    """줄 하나의 인라인 markdown 처리 — **bold**, *italic*, `code`.

    순서: 먼저 **bold** 로 분리 → 각 non-bold 조각에서 *italic* 분리 → 각 조각에서
    `code` 처리. 중첩은 최소만 지원.
    """
    out: list = []
    # 1) **bold** 분리
    for i, bold_chunk in enumerate(re.split(r"\*\*(.+?)\*\*", s)):
        if not bold_chunk:
            continue
        if i % 2 == 1:
            out.append(html.Strong(bold_chunk))
            continue
        # 2) *italic* 분리 (단, ** 는 위에서 이미 처리됨)
        for j, it_chunk in enumerate(re.split(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", bold_chunk)):
            if not it_chunk:
                continue
            if j % 2 == 1:
                out.append(html.Em(it_chunk))
                continue
            # 3) `code`
            for k, code_chunk in enumerate(re.split(r"`([^`]+?)`", it_chunk)):
                if not code_chunk:
                    continue
                out.append(html.Code(code_chunk) if k % 2 == 1 else code_chunk)
    return out


_HEADING_TAG = {1: html.H3, 2: html.H4, 3: html.H4, 4: html.H5, 5: html.H5, 6: html.H5}


def _parse_text_and_tables(text: str) -> tuple[list, list]:
    """텍스트를 버블용 블록 + 별도 렌더용 테이블로 분리.

    블록 레벨:
    - `#{1,6} 제목` → html.H3/H4/...
    - `- 항목` 연속 → html.Ul
    - `| table |` → 별도 html.Table (버블 밖)
    - 그 외 → 인라인 (bold/italic/code) + `<br>` 연결
    """
    if not text:
        return [], []

    lines = text.split("\n")
    bubble: list = []
    tables: list = []
    pending_text: list = []
    pending_list: list = []

    def flush_text():
        nonlocal pending_text
        if pending_text:
            # 후행 Br 제거
            while pending_text and isinstance(pending_text[-1], html.Br):
                pending_text.pop()
            if pending_text:
                bubble.append(html.Span(pending_text))
            pending_text = []

    def flush_list():
        nonlocal pending_list
        if pending_list:
            bubble.append(html.Ul(
                [html.Li(_inline_md(item)) for item in pending_list],
                className="c-md-ul",
            ))
            pending_list = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Table 블록
        if (
            _is_table_row(line)
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            flush_text()
            flush_list()
            header = _split_cells(line)
            j = i + 2
            data_rows = []
            while j < len(lines) and _is_table_row(lines[j]):
                data_rows.append(_split_cells(lines[j]))
                j += 1
            tables.append(_render_md_table(header, data_rows))
            i = j
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue

        # Heading 블록
        heading_m = _HEADING_RE.match(line)
        if heading_m:
            flush_text()
            flush_list()
            level = len(heading_m.group(1))
            content = heading_m.group(2)
            tag = _HEADING_TAG.get(level, html.H4)
            bubble.append(tag(_inline_md(content), className="c-md-h"))
            i += 1
            continue

        # List item (연속해서 모음)
        list_m = _LIST_RE.match(line)
        if list_m:
            flush_text()
            pending_list.append(list_m.group(1))
            i += 1
            continue

        # 빈 줄 — 리스트/텍스트 블록 종료 신호
        if not line.strip():
            flush_list()
            # 텍스트 내부의 빈 줄은 단락 분리 — Br 두 번
            if pending_text and not (pending_text and isinstance(pending_text[-1], html.Br)):
                pending_text.append(html.Br())
            i += 1
            continue

        # 일반 텍스트 (인라인 markdown + 줄바꿈)
        flush_list()
        if pending_text and not isinstance(pending_text[-1], html.Br):
            pending_text.append(html.Br())
        pending_text.extend(_inline_md(line))
        i += 1

    flush_list()
    flush_text()
    return bubble, tables


def _render_md_table(header: list[str], data_rows: list[list[str]], max_rows: int = 20) -> html.Div:
    display = data_rows[:max_rows]
    truncated = len(data_rows) > max_rows
    head = html.Thead(html.Tr([html.Th(h) for h in header]))
    tbody = html.Tbody(
        [html.Tr([html.Td(c) for c in row]) for row in display]
    )
    footer: list = []
    if truncated:
        footer.append(
            html.Div(f"외 {len(data_rows) - max_rows:,}건", className="c-table-foot")
        )
    return html.Div(
        className="c-table",
        children=[
            html.Div(
                className="c-table-wrap",
                children=html.Table(className="c-tab", children=[head, tbody]),
            ),
            *footer,
        ],
    )


# 하위 호환 (다른 곳에서 호출되는 경우 대비)
def _clean_markdown(text: str) -> list:
    return _parse_text_and_tables(text)[0]


def _render_message(m: dict) -> html.Div:
    role = m.get("role", "sys")
    kind = m.get("kind")

    if role == "sys" and kind == "welcome":
        return welcome_msg()

    if role == "sys" and kind == "typing":
        return html.Div(
            className="c-msg sys",
            children=[
                html.Div(className="av", children=_fa("robot")),
                html.Div(
                    className="bub",
                    children=html.Div(
                        className="c-type",
                        children=[html.Span(), html.Span(), html.Span()],
                    ),
                ),
            ],
        )

    if role == "user":
        return html.Div(
            className="c-msg user",
            children=[
                html.Div(className="av", children=_fa("user")),
                html.Div(className="bub", children=m.get("text", "")),
            ],
        )

    bubble_parts, md_tables = _parse_text_and_tables(m.get("text", ""))
    body: list = [html.Div(className="bub", children=bubble_parts)]
    if m.get("chart"):
        try:
            fig = go.Figure(json.loads(m["chart"]))
            charts.apply_dark_theme(fig, margin=dict(l=30, r=10, t=20, b=30))
            body.append(
                html.Div(
                    className="c-chart",
                    children=dcc.Graph(
                        figure=fig,
                        config={"displayModeBar": False, "responsive": True},
                        style={"height": 220},
                    ),
                )
            )
        except Exception:
            pass
    # 1) 답변 텍스트에 포함된 markdown 테이블 (LLM 이 직접 작성한 경우)
    body.extend(md_tables)
    # 2) sql_rows 기반 구조화 테이블 (markdown 테이블이 없을 때만 중복 방지)
    if m.get("table") and not md_tables:
        body.append(_render_table(m["table"]))
    return html.Div(
        className="c-msg sys",
        children=[
            html.Div(className="av", children=_fa("robot")),
            html.Div(children=body),
        ],
    )


def _render_table(rows: list[dict], max_rows: int = 10) -> html.Div:
    """SQL 결과 dict 리스트 → 컴팩트 HTML 테이블.

    채팅 버블에 내장되므로 높이 제한(최대 max_rows 행 + "외 N건" 주석).
    """
    if not rows:
        return html.Div()
    columns = list(rows[0].keys())
    display = rows[:max_rows]
    truncated = len(rows) > max_rows

    def _fmt(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:,.2f}".rstrip("0").rstrip(".") if "." in f"{v:.2f}" else f"{v:,.0f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    head = html.Thead(html.Tr([html.Th(c) for c in columns]))
    tbody = html.Tbody(
        [
            html.Tr([html.Td(_fmt(r.get(c))) for c in columns])
            for r in display
        ]
    )
    footer: list = []
    if truncated:
        footer.append(
            html.Div(
                f"외 {len(rows) - max_rows:,}건",
                className="c-table-foot",
            )
        )

    return html.Div(
        className="c-table",
        children=[
            html.Div(
                className="c-table-wrap",
                children=html.Table(className="c-tab", children=[head, tbody]),
            ),
            *footer,
        ],
    )


# --- Chat panel: 4단계 크기 전환 상태 머신 (스펙 6.3) ---
@callback(
    Output("chat-size-mode", "data"),
    Output("chat-prev-size", "data"),
    Input("chat-open", "n_clicks"),
    Input({"role": "chat-size", "mode": ALL}, "n_clicks"),
    Input("chat-esc-trigger", "data"),
    State("chat-size-mode", "data"),
    State("chat-prev-size", "data"),
    prevent_initial_call=True,
)
def _chat_size_transition(_open, _size_clicks, _esc, cur, prev):
    from dash_app.components.chat_panel.sizes import next_mode_down

    trig = ctx.triggered_id
    cur = cur or "minimized"
    prev = prev or "compact"

    if trig == "chat-open":
        # minimized 상태에서 열기 — 이전 크기(없으면 compact) 로 복귀
        new = prev if cur == "minimized" and prev != "minimized" else cur
        if new == "minimized":
            new = "compact"
        return new, cur
    if isinstance(trig, dict) and trig.get("role") == "chat-size":
        # 4단계 직접 선택 — 초기 렌더 n_clicks=None 으로 인한 오트리거 방지
        if not any(_size_clicks or []):
            raise PreventUpdate
        new_mode = trig.get("mode", cur)
        if new_mode == cur:
            raise PreventUpdate
        return new_mode, cur
    if trig == "chat-esc-trigger":
        new = next_mode_down(cur)
        if new == cur:
            raise PreventUpdate
        return new, cur
    raise PreventUpdate


# --- 4단계 직접 선택 버튼: 현재 mode 강조 ---
@callback(
    Output("chat-panel", "data-size"),
    Output({"role": "chat-size", "mode": ALL}, "className"),
    Input("chat-size-mode", "data"),
    State({"role": "chat-size", "mode": ALL}, "id"),
)
def _chat_apply_size(mode, ids):
    mode = mode or "minimized"
    classes = [
        "hdr-btn" + (" on" if i["mode"] == mode else "")
        for i in ids
    ]
    return mode, classes


def _append_user_message(msgs: list, thread: str | None, text: str) -> tuple[list, str]:
    msgs = list(msgs or [])
    msgs.append({"role": "user", "text": text})
    msgs.append({"role": "sys", "kind": "typing"})
    if not thread:
        thread = str(uuid.uuid4())
    return msgs, thread


def _build_message_history(msgs: list) -> list:
    """채팅 store 의 메시지 이력을 LangChain 메시지 리스트로 변환한다.

    Dash background 콜백은 매 호출마다 새 프로세스에서 실행되어 InMemorySaver
    의 체크포인트가 유실되므로, 멀티턴 문맥을 state["messages"] 에 직접 실어
    보낸다. query_generator·synthesize 는 `[-8:]` 로 자체 슬라이싱함.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    history: list = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        text = (m.get("text") or "").strip()
        if not text:
            continue
        role = m.get("role")
        kind = m.get("kind")
        if role == "user":
            history.append(HumanMessage(content=text))
        elif role == "sys" and kind == "answer":
            history.append(AIMessage(content=text))
    return history


# --- Chat: send button or Enter key ---
@callback(
    Output("chat-msgs", "data"),
    Output("chat-input", "value"),
    Output("chat-busy", "data"),
    Output("chat-thread", "data"),
    Input("chat-send", "n_clicks"),
    State("chat-input", "value"),
    State("chat-msgs", "data"),
    State("chat-busy", "data"),
    State("chat-thread", "data"),
    prevent_initial_call=True,
)
def _chat_submit_send(n_clicks, input_val, msgs, busy, thread):
    if not n_clicks or busy:
        raise PreventUpdate
    text = (input_val or "").strip()
    if not text:
        raise PreventUpdate
    new_msgs, new_thread = _append_user_message(msgs, thread, text)
    return new_msgs, "", True, new_thread


# --- Chat: chip click (독립 콜백으로 분리 — send 트리거 혼선 방지) ---
@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-busy", "data", allow_duplicate=True),
    Output("chat-thread", "data", allow_duplicate=True),
    Input({"role": "chat-chip", "value": ALL}, "n_clicks"),
    State("chat-msgs", "data"),
    State("chat-busy", "data"),
    State("chat-thread", "data"),
    prevent_initial_call=True,
)
def _chat_submit_chip(chip_clicks, msgs, busy, thread):
    if busy:
        raise PreventUpdate
    # 최초 렌더 시 n_clicks=None 으로 잘못 트리거되는 것을 방지
    if not any(chip_clicks or []):
        raise PreventUpdate
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or trig.get("role") != "chat-chip":
        raise PreventUpdate
    text = trig.get("value", "").strip()
    if not text:
        raise PreventUpdate
    new_msgs, new_thread = _append_user_message(msgs, thread, text)
    return new_msgs, True, new_thread


# --- Chat: invoke graph when busy=True ---
# 설계 원칙: 채팅 서비스는 페이지 필터(사이드바·선택된 시군구 등)와 무관하게
# DB 전체를 커버한다. 사용자 질문만 그대로 에이전트에 전달하고, 지역·기간·
# 거래유형 등은 질문 안에서 자연어로 명시하게 한다.
#
# background=True — 장시간 실행(30초+) 중에 `chat-cancel` 버튼으로 중단 가능.
# running — 실행 중 send 버튼 비활성 + cancel 버튼 표시.
@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-busy", "data", allow_duplicate=True),
    Input("chat-busy", "data"),
    State("chat-msgs", "data"),
    State("chat-thread", "data"),
    background=True,
    cancel=[Input("chat-cancel", "n_clicks")],
    running=[
        (Output("chat-send", "disabled"), True, False),
        (Output("chat-send", "style"), {"display": "none"}, {}),
        (Output("chat-cancel", "style"), {"display": "flex"}, {"display": "none"}),
        (Output("chat-input", "disabled"), True, False),
    ],
    prevent_initial_call=True,
)
def _chat_invoke(busy, msgs, thread):
    if not busy:
        raise PreventUpdate
    if not msgs or msgs[-1].get("kind") != "typing":
        return no_update, False
    history = _build_message_history(msgs[:-1])
    if not history or not any(m.type == "human" for m in history):
        msgs = msgs[:-1]
        return msgs, False

    try:
        graph = _get_graph()
        final_text = ""
        chart_json = None
        table_rows: list[dict] | None = None
        for event in graph.stream(
            {"messages": history},
            {"recursion_limit": 50, "configurable": {"thread_id": thread}},
            stream_mode="updates",
        ):
            for node_name, update in event.items():
                if not update:
                    continue
                if node_name == "chart_node" and update.get("chart_data"):
                    chart_json = update["chart_data"]
                # sql_node 가 구조화된 rows 를 state 에 넣어둠 — 테이블 렌더용으로 캡처
                if node_name == "sql_node" and update.get("sql_rows"):
                    rows = update["sql_rows"]
                    if isinstance(rows, list) and rows:
                        table_rows = rows
                if node_name == "synthesize":
                    synth_msgs = update.get("messages") or []
                    if synth_msgs:
                        raw = synth_msgs[-1].content
                        if isinstance(raw, list):
                            parts = []
                            for p in raw:
                                if isinstance(p, dict):
                                    parts.append(p.get("text", ""))
                                else:
                                    parts.append(str(p))
                            final_text = "".join(parts)
                        else:
                            final_text = str(raw)
        if not final_text:
            final_text = "응답을 생성하지 못했어요. 다시 시도해 주세요."
    except Exception as e:
        final_text = f"오류가 발생했습니다: {e}"
        chart_json = None
        table_rows = None

    msgs = msgs[:-1] + [
        {
            "role": "sys",
            "kind": "answer",
            "text": final_text,
            "chart": chart_json,
            "table": table_rows,
        }
    ]
    return msgs, False


# --- Chat: render messages from store ---
@callback(Output("chat-scroll", "children"), Input("chat-msgs", "data"))
def _chat_render(msgs):
    if not msgs:
        return [welcome_msg()]
    return [_render_message(m) for m in msgs]


@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-busy", "data", allow_duplicate=True),
    Input("chat-cancel", "n_clicks"),
    State("chat-msgs", "data"),
    prevent_initial_call=True,
)
def _chat_cancel(n, msgs):
    """중단 버튼 — typing placeholder 를 '중단됨' 으로 교체하고 busy 해제."""
    if not n:
        raise PreventUpdate
    msgs = list(msgs or [])
    if msgs and msgs[-1].get("kind") == "typing":
        msgs = msgs[:-1] + [
            {
                "role": "sys",
                "kind": "answer",
                "text": "*(사용자가 중단함)*",
            }
        ]
    return msgs, False


# 채팅 헤더의 badge 는 "실시간 · DB 전체" 고정 — 채팅은 페이지 필터와 분리된 스코프.
