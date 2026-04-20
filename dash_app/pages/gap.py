"""호가 괴리 페이지 (/gap). Phase C 에서 구현."""

from __future__ import annotations

import dash

from dash_app.pages._skeleton import skeleton

dash.register_page(
    __name__,
    path="/gap",
    name="호가 괴리",
    order=4,
    title="APT Insight — 호가 괴리",
)

layout = skeleton(
    title="호가 괴리",
    description="실거래가 대비 호가의 괴리율 분포와 의심 단지를 조회합니다.",
)
