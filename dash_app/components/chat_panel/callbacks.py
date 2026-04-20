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
from dash_app.config import DEAL_LABELS

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


def _scope_text(sido: str, sgg: str, dong: str) -> str:
    if dong and dong != "전체":
        return f"{sido} · {sgg} · {dong}"
    if sgg and sgg != "전체":
        return f"{sido} · {sgg}"
    return sido


def _clean_markdown(text: str) -> list:
    if not text:
        return []
    parts: list = []
    chunks = re.split(r"\*\*(.+?)\*\*", text)
    for i, c in enumerate(chunks):
        if not c:
            continue
        if i % 2 == 1:
            parts.append(html.Strong(c))
        else:
            lines = c.split("\n")
            for j, line in enumerate(lines):
                if j:
                    parts.append(html.Br())
                parts.append(line)
    return parts


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

    body = [html.Div(className="bub", children=_clean_markdown(m.get("text", "")))]
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
    return html.Div(
        className="c-msg sys",
        children=[
            html.Div(className="av", children=_fa("robot")),
            html.Div(children=body),
        ],
    )


# --- Chat panel: open/close + size ---
@callback(
    Output("chat-panel", "className"),
    Output("chat-panel", "data-size"),
    Output({"role": "chat-size", "value": ALL}, "className"),
    Input("chat-fab", "n_clicks"),
    Input("chat-close", "n_clicks"),
    Input({"role": "chat-size", "value": ALL}, "n_clicks"),
    State("chat-panel", "className"),
    State("chat-panel", "data-size"),
    State({"role": "chat-size", "value": ALL}, "id"),
    prevent_initial_call=True,
)
def _chat_visibility(_fab, _close, _size_clicks, cur_class, cur_size, size_ids):
    trig = ctx.triggered_id
    cur_size = cur_size or "compact"
    is_hidden = cur_class and "hidden" in cur_class

    if trig == "chat-fab":
        new_class = "chat-panel"
        new_size = cur_size
    elif trig == "chat-close":
        new_class = "chat-panel hidden"
        new_size = cur_size
    elif isinstance(trig, dict) and trig.get("role") == "chat-size":
        new_class = "chat-panel" if not is_hidden else "chat-panel"
        new_size = trig["value"]
    else:
        raise PreventUpdate

    on_classes = ["on" if i["value"] == new_size else "" for i in size_ids]
    return new_class, new_size, on_classes


# --- Chat: user send or chip click ---
@callback(
    Output("chat-msgs", "data"),
    Output("chat-input", "value"),
    Output("chat-busy", "data"),
    Output("chat-thread", "data"),
    Input("chat-send", "n_clicks"),
    Input({"role": "chat-chip", "value": ALL}, "n_clicks"),
    State("chat-input", "value"),
    State("chat-msgs", "data"),
    State("chat-busy", "data"),
    State("chat-thread", "data"),
    prevent_initial_call=True,
)
def _chat_submit(_send, _chip_clicks, input_val, msgs, busy, thread):
    if busy:
        raise PreventUpdate

    trig = ctx.triggered_id
    text = None
    if trig == "chat-send":
        text = (input_val or "").strip()
    elif isinstance(trig, dict) and trig.get("role") == "chat-chip":
        text = trig["value"]

    if not text:
        raise PreventUpdate

    msgs = list(msgs or [])
    msgs.append({"role": "user", "text": text})
    msgs.append({"role": "sys", "kind": "typing"})

    if not thread:
        thread = str(uuid.uuid4())

    return msgs, "", True, thread


# --- Chat: invoke graph when busy=True ---
@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-busy", "data", allow_duplicate=True),
    Input("chat-busy", "data"),
    State("chat-msgs", "data"),
    State("chat-thread", "data"),
    State("f-sido", "value"),
    State("f-sgg", "value"),
    State("f-dong", "value"),
    State("f-area", "value"),
    State("f-deal", "data"),
    State("f-period", "value"),
    prevent_initial_call=True,
)
def _chat_invoke(busy, msgs, thread, sido, sgg, dong, area, deal, period):
    if not busy:
        raise PreventUpdate
    if not msgs or msgs[-1].get("kind") != "typing":
        return no_update, False
    user_msg = None
    for m in reversed(msgs[:-1]):
        if m.get("role") == "user":
            user_msg = m.get("text")
            break
    if not user_msg:
        msgs = msgs[:-1]
        return msgs, False

    scope = _scope_text(sido or "서울특별시", sgg or "전체", dong or "전체")
    ctx_line = (
        f"(현재 조회: {scope} · {DEAL_LABELS.get(deal, deal)} · {area} · 최근 {period}개월)"
    )
    prompt = f"{user_msg}\n\n{ctx_line}"

    try:
        from langchain_core.messages import HumanMessage

        graph = _get_graph()
        final_text = ""
        chart_json = None
        for event in graph.stream(
            {"messages": [HumanMessage(content=prompt)]},
            {"recursion_limit": 50, "configurable": {"thread_id": thread}},
            stream_mode="updates",
        ):
            for node_name, update in event.items():
                if not update:
                    continue
                if node_name == "chart_node" and update.get("chart_data"):
                    chart_json = update["chart_data"]
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

    msgs = msgs[:-1] + [
        {"role": "sys", "kind": "answer", "text": final_text, "chart": chart_json}
    ]
    return msgs, False


# --- Chat: render messages from store ---
@callback(Output("chat-scroll", "children"), Input("chat-msgs", "data"))
def _chat_render(msgs):
    if not msgs:
        return [welcome_msg()]
    return [_render_message(m) for m in msgs]


# --- Chat: scope badge ---
@callback(
    Output("chat-scope", "children"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
)
def _chat_scope(sido, sgg):
    loc = sgg if sgg and sgg != "전체" else (sido or "—")
    return [html.Span(className="dot-live"), f"실시간 · {loc}"]
