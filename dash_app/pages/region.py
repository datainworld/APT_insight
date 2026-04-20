"""지역 심층 페이지 (/region). Phase C 에서 구현."""

from __future__ import annotations

import dash

from dash_app.pages._skeleton import skeleton

dash.register_page(
    __name__,
    path="/region",
    name="지역 심층",
    order=2,
    title="APT Insight — 지역 심층",
)

layout = skeleton(
    title="지역 심층",
    description="선택한 시군구의 KPI, choropleth, 단지 랭킹을 심층 분석합니다.",
)
