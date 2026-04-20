"""뉴스 & RAG 페이지 (/insight). Phase C 에서 구현."""

from __future__ import annotations

import dash

from dash_app.pages._skeleton import skeleton

dash.register_page(
    __name__,
    path="/insight",
    name="뉴스 & RAG",
    order=6,
    title="APT Insight — 뉴스 & RAG",
)

layout = skeleton(
    title="뉴스 & RAG",
    description="최근 뉴스 타임라인과 PDF 문서 기반 RAG 검색을 제공합니다.",
)
