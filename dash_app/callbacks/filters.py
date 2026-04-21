"""전역 필터 cascade 콜백 — 모든 페이지가 공유하는 사이드바 필터 동작.

app.py 가 import 하면 side-effect 로 등록된다.
"""

from __future__ import annotations

from dash import ALL, Input, Output, State, callback, ctx, html

from dash_app.queries import rt_queries as q


def _format_period(months: int) -> list:
    if months >= 12:
        years = months / 12
        txt = f"{years:.0f}" if months % 12 == 0 else f"{years:.1f}"
        return [txt, html.Span("년", className="unit")]
    return [str(months), html.Span("개월", className="unit")]


@callback(
    Output("f-sgg", "options"),
    Output("f-sgg", "value"),
    Input("f-sido", "value"),
)
def _cascade_sgg(sido: str | None):
    sggs = q.list_sgg(sido) if sido else ()
    opts = [{"label": "전체", "value": "전체"}] + [
        {"label": s, "value": s} for s in sggs
    ]
    return opts, "전체"


@callback(
    Output("f-period-label", "children"),
    Input("f-period", "value"),
)
def _period_label(v):
    return _format_period(int(v or 36))


@callback(
    Output("f-deal", "data"),
    Output({"role": "seg-deal", "value": ALL}, "className"),
    Input({"role": "seg-deal", "value": ALL}, "n_clicks"),
    State({"role": "seg-deal", "value": ALL}, "id"),
    State("f-deal", "data"),
)
def _deal_seg(n_clicks, ids, current):
    trig = ctx.triggered_id
    if not trig or not any(n_clicks):
        picked = current or "sale"
    else:
        picked = trig["value"]
    return picked, ["on" if i["value"] == picked else "" for i in ids]
