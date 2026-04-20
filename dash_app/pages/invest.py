"""투자 지표 페이지 (/invest). Phase C 에서 구현."""

from __future__ import annotations

import dash

from dash_app.pages._skeleton import skeleton

dash.register_page(
    __name__,
    path="/invest",
    name="투자 지표",
    order=5,
    title="APT Insight — 투자 지표",
)

layout = skeleton(
    title="투자 지표",
    description="전세가율, 갭, 전월세전환율 등 갭투자 매력도 지표를 제공합니다.",
)
