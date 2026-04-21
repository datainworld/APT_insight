"""필터 사이드바 — 시도·시군구·면적·거래유형·기간.

단순화 이력:
- 읍면동(f-dong) 제거: 시군구 단위까지만 필터링.
- btn-apply / btn-reset 제거: 모든 드롭다운 변경이 즉시 콜백을 트리거.
- 기간 슬라이더 max=36 (최근 3년).
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
                                max=36,
                                step=1,
                                value=36,
                                marks={3: "3M", 6: "6M", 12: "1Y", 24: "2Y", 36: "3Y"},
                                tooltip={"always_visible": False, "placement": "bottom"},
                                included=True,
                            ),
                        ],
                    ),
                ],
            ),
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
