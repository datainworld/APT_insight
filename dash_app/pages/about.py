"""소개 페이지 (/about). Phase E 에서 구현."""

from __future__ import annotations

import dash

from dash_app.pages._skeleton import skeleton

dash.register_page(
    __name__,
    path="/about",
    name="소개",
    order=7,
    title="APT Insight — 소개",
)

layout = skeleton(
    title="APT Insight 소개",
    description="시스템 개요, 데이터 소스, 핵심 지표 해설, AI 채팅·RAG 사용법을 안내합니다.",
    phase="Phase E",
)
