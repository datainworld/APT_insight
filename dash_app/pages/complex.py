"""단지 상세 페이지 (/complex). Phase C 에서 구현."""

from __future__ import annotations

import dash

from dash_app.pages._skeleton import skeleton

dash.register_page(
    __name__,
    path="/complex",
    name="단지 상세",
    order=3,
    title="APT Insight — 단지 상세",
)

layout = skeleton(
    title="단지 상세",
    description="단지별 실거래·호가·전월세·층×면적 매트릭스를 탭으로 제공합니다.",
)
