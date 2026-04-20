"""플로팅 채팅 패널 레이아웃 — 기존 chat_components() 이동.

**주의**: 본 파일은 Phase D 에서 4단계 크기 전환 패널로 전면 재작성된다.
Phase A/B 시점에는 기존 UI 그대로 유지하여 홈 페이지 회귀를 막는 역할만 한다.
"""

from __future__ import annotations

from dash import dcc, html

from dash_app.config import CHIP_PROMPTS


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


def chat_components() -> list:
    """FAB + panel. Rendered at the app shell root so position:fixed works."""
    return [
        html.Button(
            [html.Span(className="pulse"), _fa("comment-dots")],
            id="chat-fab",
            className="chat-fab",
            n_clicks=0,
            title="AI 어시스턴트",
        ),
        html.Section(
            id="chat-panel",
            className="chat-panel hidden",
            **{"data-size": "compact"},  # type: ignore[arg-type]
            children=[
                html.Header(
                    className="chat-hdr",
                    children=[
                        html.Div(className="avatar", children=_fa("robot")),
                        html.Div(
                            className="title",
                            children=[
                                "AI 어시스턴트",
                                html.Em(
                                    id="chat-scope",
                                    children=[
                                        html.Span(className="dot-live"),
                                        "실시간 · 서울특별시",
                                    ],
                                ),
                            ],
                        ),
                        html.Button(
                            _fa("regular fa-square"),
                            id={"role": "chat-size", "value": "compact"},
                            className="on",
                            title="컴팩트",
                            n_clicks=0,
                        ),
                        html.Button(
                            _fa("table-columns"),
                            id={"role": "chat-size", "value": "expanded"},
                            title="확장",
                            n_clicks=0,
                        ),
                        html.Button(
                            _fa("up-right-and-down-left-from-center"),
                            id={"role": "chat-size", "value": "max"},
                            title="최대화",
                            n_clicks=0,
                        ),
                        html.Button(
                            _fa("xmark"),
                            id="chat-close",
                            title="닫기",
                            n_clicks=0,
                        ),
                    ],
                ),
                html.Div(
                    id="chat-scroll",
                    className="chat-scroll",
                    children=[welcome_msg()],
                ),
                html.Div(
                    className="chat-input",
                    children=[
                        html.Div(
                            className="wrap",
                            children=[
                                dcc.Textarea(
                                    id="chat-input",
                                    placeholder="조건에 맞는 분석을 물어보세요…",
                                    rows=1,
                                ),
                                html.Button(
                                    _fa("paper-plane"),
                                    id="chat-send",
                                    className="btn-s",
                                    n_clicks=0,
                                ),
                            ],
                        ),
                    ],
                ),
                dcc.Store(id="chat-msgs", data=[{"role": "sys", "kind": "welcome"}]),
                dcc.Store(id="chat-thread", storage_type="session"),
                dcc.Store(id="chat-busy", data=False),
            ],
        ),
    ]


def welcome_msg() -> html.Div:
    return html.Div(
        className="c-msg sys",
        children=[
            html.Div(className="av", children=_fa("robot")),
            html.Div(
                children=[
                    html.Div(
                        className="bub",
                        children=[
                            "안녕하세요! 이 창은 ",
                            html.Strong("플로팅 패널"),
                            "입니다. 상단 버튼으로 컴팩트 / 확장 / 최대화를 전환하세요.",
                        ],
                    ),
                    html.Div(
                        className="c-chips",
                        children=[
                            html.Button(
                                p,
                                id={"role": "chat-chip", "value": p},
                                className="c-chip",
                                n_clicks=0,
                            )
                            for p in CHIP_PROMPTS
                        ],
                    ),
                ],
            ),
        ],
    )
