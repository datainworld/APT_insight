"""필터 사이드바 — 시도·시군구·동·면적·거래유형·기간.

기존 components.sidebar() 를 이동한 것으로, 컨트롤 ID는 전역 유일(`f-*`)이다.
페이지가 필터를 필요로 하지 않으면 상위에서 렌더하지 않는다.
"""

from __future__ import annotations

from datetime import date

from dash import dcc, html

from dash_app.config import AREA_OPTIONS, DEAL_OPTIONS, DEFAULT_SIDO, SIDO_OPTIONS


def _fa(icon: str, extra: str = "") -> html.I:
    return html.I(className=f"fa-solid fa-{icon} {extra}".strip())


def filter_panel(
    initial_sido: str = DEFAULT_SIDO,
    last_refresh: date | None = None,
) -> html.Div:
    return html.Div(
        className="filter-body",
        children=[
            html.Div(
                className="filter-title",
                children=[html.Span(_fa("check"), className="dot"), "조건 필터링"],
            ),
            html.Div(
                className="filter-stack",
                children=[
                    html.Div(
                        className="filter-group",
                        children=[
                            html.Label("시도"),
                            dcc.Dropdown(
                                id="f-sido",
                                options=SIDO_OPTIONS,
                                value=initial_sido,
                                clearable=False,
                                searchable=False,
                                className="select",
                            ),
                        ],
                    ),
                    html.Div(
                        className="filter-group",
                        children=[
                            html.Label("자치구"),
                            dcc.Dropdown(
                                id="f-sgg",
                                options=[{"label": "전체", "value": "전체"}],
                                value="전체",
                                clearable=False,
                                searchable=True,
                                className="select",
                            ),
                        ],
                    ),
                    html.Div(
                        className="filter-group",
                        children=[
                            html.Label("읍면동"),
                            dcc.Dropdown(
                                id="f-dong",
                                options=[{"label": "전체", "value": "전체"}],
                                value="전체",
                                clearable=False,
                                searchable=True,
                                className="select",
                            ),
                        ],
                    ),
                    html.Div(
                        className="filter-group",
                        children=[
                            html.Label("면적(㎡)"),
                            dcc.Dropdown(
                                id="f-area",
                                options=AREA_OPTIONS,
                                value="전체",
                                clearable=False,
                                searchable=False,
                                className="select",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="filter-group",
                children=[
                    html.Label("거래 유형"),
                    html.Div(
                        className="seg",
                        children=[
                            html.Button(
                                label,
                                id={"role": "seg-deal", "value": key},
                                className="on" if key == "sale" else "",
                                n_clicks=0,
                            )
                            for key, label in DEAL_OPTIONS
                        ],
                    ),
                    dcc.Store(id="f-deal", data="sale"),
                ],
            ),
            html.Div(
                className="filter-group",
                children=[
                    html.Div(
                        className="period-head",
                        children=[
                            html.Label("기간", style={"marginBottom": 0}),
                            html.Div(
                                id="f-period-label",
                                className="val",
                                children=["36", html.Span("개월", className="unit")],
                            ),
                        ],
                    ),
                    html.Div(
                        className="period-wrap",
                        children=[
                            dcc.Slider(
                                id="f-period",
                                min=1,
                                max=120,
                                step=1,
                                value=36,
                                marks={6: "6M", 12: "1Y", 36: "3Y", 60: "5Y", 120: "전체"},
                                tooltip={"always_visible": False, "placement": "bottom"},
                                included=True,
                            ),
                        ],
                    ),
                ],
            ),
            html.Button(
                [_fa("filter"), " 조건 적용"],
                id="btn-apply",
                className="btn-apply",
                n_clicks=0,
            ),
            html.Button("초기화", id="btn-reset", className="btn-reset", n_clicks=0),
            html.Div(
                className="stamp",
                children=[
                    html.Div("마지막 갱신"),
                    html.Div(
                        last_refresh.strftime("%Y-%m-%d") if last_refresh else "—",
                        style={"color": "var(--fg-1)"},
                    ),
                ],
            ),
        ],
    )
