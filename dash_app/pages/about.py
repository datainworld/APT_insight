"""소개 페이지 (/about) — 스펙 3.7.

단일 컬럼 880px 중앙 정렬, 8 섹션:
1. 히어로 (소개 + CTA)
2. 주요 기능 카드 그리드
3. 데이터 소스 (SVG 다이어그램 + 커버리지)
4. 핵심 지표 해설 (GLOSSARY 전체)
5. AI 채팅 4단계 크기 + 예시
6. PDF RAG 활용법
7. 기술 스택
8. 버전·문의
"""

from __future__ import annotations

import dash
from dash import dcc, html

from dash_app.components.formatters import format_count
from dash_app.config import CHIP_PROMPTS, PAGES
from dash_app.glossary.terms import GLOSSARY
from dash_app.queries.coverage_queries import get_coverage, get_pdf_count

dash.register_page(
    __name__,
    path="/about",
    name="소개",
    order=5,
    title="APT Insight — 소개",
)


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


# ---------------------------------------------------------------------------
# 섹션 1. 히어로
# ---------------------------------------------------------------------------


def _section_hero() -> html.Section:
    return html.Section(
        className="about-hero",
        children=[
            html.Div(className="about-logo", children=_fa("building")),
            html.H1("APT Insight"),
            html.P(
                "수도권 아파트 실거래가 · 매물 · 뉴스를 한 화면에서 분석하고, "
                "AI 채팅으로 자연어 질의까지 가능한 부동산 분석 대시보드.",
                className="about-lead",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 섹션 2. 주요 기능
# ---------------------------------------------------------------------------


_FEATURE_DESC = {
    "/": "수도권 시군구 지표를 한눈에 — 거래량·단위면적가·전세가율·활성 매물",
    "/complex": "개별 단지의 실거래·호가·전월세·층별 매트릭스",
    "/gap": "실거래가 대비 호가 괴리율로 시장 과열/저평가 단지 탐지",
    "/invest": "전세가율 · 갭 · 전월세전환율 기반 갭투자 매력도 점수",
}


def _section_features() -> html.Section:
    return html.Section(
        className="about-section",
        children=[
            html.H2("주요 기능"),
            html.Div(
                className="about-grid",
                children=[
                    dcc.Link(
                        href=p["path"],
                        className="about-card",
                        children=[
                            html.Div(_fa(p["icon"]), className="about-card-ic"),
                            html.B(p["name"]),
                            html.P(_FEATURE_DESC.get(p["path"], ""), className="about-card-desc"),
                        ],
                    )
                    for p in PAGES
                    if p["path"] != "/about"
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 섹션 3. 데이터 소스
# ---------------------------------------------------------------------------


def _section_data_sources() -> html.Section:
    cov = get_coverage()
    pdf_n = get_pdf_count()

    def _stat(label: str, value: str, note: str = "") -> html.Div:
        return html.Div(
            className="about-stat",
            children=[
                html.Div(value, className="about-stat-v"),
                html.Div(label, className="about-stat-l"),
                html.Div(note, className="about-stat-n") if note else None,
            ],
        )

    return html.Section(
        className="about-section",
        children=[
            html.H2("데이터 소스"),
            html.P(
                "3개의 외부 공공/상업 데이터 소스를 일일 수집해 통합 질의합니다.",
                className="about-para",
            ),
            html.Div(
                className="about-stats",
                children=[
                    _stat("단지 (국토부)", format_count(cov.get("rt_complex")), "rt_complex"),
                    _stat("매매 실거래", format_count(cov.get("rt_trade")), "rt_trade · 36M"),
                    _stat("전월세 실거래", format_count(cov.get("rt_rent")), "rt_rent · 36M"),
                    _stat("네이버 활성 매물", format_count(cov.get("nv_active")), "nv_listing"),
                    _stat("단지 매핑", format_count(cov.get("mapping")), "complex_mapping"),
                    _stat("뉴스 기사", format_count(cov.get("news")), "news_articles (수집 7d)"),
                    _stat("PDF 문서", format_count(pdf_n), "PGVector langchain_pg_embedding"),
                ],
            ),
            html.Div(
                className="about-flow",
                children=[
                    html.Div(
                        className="flow-box flow-src",
                        children=[_fa("database"), html.B("국토부 실거래가"), html.P("매매 · 전월세")],
                    ),
                    html.Div(
                        className="flow-box flow-src",
                        children=[_fa("globe"), html.B("네이버 부동산"), html.P("활성 매물 · 호가")],
                    ),
                    html.Div(
                        className="flow-box flow-src",
                        children=[_fa("newspaper"), html.B("네이버 뉴스"), html.P("실시간 기사")],
                    ),
                    html.Div(_fa("arrow-right-long"), className="flow-arrow"),
                    html.Div(
                        className="flow-box flow-db",
                        children=[
                            _fa("server"),
                            html.B("APT Insight DB"),
                            html.P("PostgreSQL + pgvector"),
                        ],
                    ),
                    html.Div(_fa("arrow-right-long"), className="flow-arrow"),
                    html.Div(
                        className="flow-box flow-agent",
                        children=[
                            _fa("robot"),
                            html.B("SQL · RAG · News 에이전트"),
                            html.P("LangGraph supervisor"),
                        ],
                    ),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 섹션 4. 핵심 지표 해설 (GLOSSARY iterate)
# ---------------------------------------------------------------------------


def _section_glossary() -> html.Section:
    rows = []
    for _, term in GLOSSARY.items():
        children: list = [
            html.B(term["label"]),
            html.P(term["long"] or term["short"], className="term-long"),
        ]
        if term.get("formula"):
            children.append(html.Code(term["formula"], className="term-formula"))
        if term.get("example"):
            children.append(
                html.Div(
                    [html.Span("예시 · ", className="term-label"), term["example"]],
                    className="term-example",
                )
            )
        rows.append(html.Div(className="term-item", children=children))

    return html.Section(
        className="about-section",
        children=[
            html.H2("핵심 지표 해설"),
            html.P(
                "대시보드와 AI 답변에서 자주 등장하는 용어. 정의 · 산식 · 예시.",
                className="about-para",
            ),
            html.Div(className="term-list", children=rows),
        ],
    )


# ---------------------------------------------------------------------------
# 섹션 5. AI 채팅 사용법
# ---------------------------------------------------------------------------


def _section_chat() -> html.Section:
    sizes = [
        ("minimized", "최소화", "아이콘 56×56, 우하단 고정"),
        ("compact", "컴팩트", "400×640, 기본 열림 상태"),
        ("expanded", "확장", "우측 도크 · 전체 높이"),
        ("maximized", "최대화", "전체 화면 — 긴 차트·테이블 용"),
    ]
    return html.Section(
        className="about-section",
        children=[
            html.H2("AI 채팅 사용법"),
            html.P(
                "자연어로 DB 전체를 질의. 지역·기간·거래유형은 질문 안에서 직접 언급하세요.",
                className="about-para",
            ),
            html.Div(
                className="about-sizes",
                children=[
                    html.Div(
                        className="size-item",
                        children=[
                            html.Code(key, className="size-code"),
                            html.B(label),
                            html.P(desc),
                        ],
                    )
                    for key, label, desc in sizes
                ],
            ),
            html.Div(
                className="about-examples",
                children=[
                    html.Div("예시 질문", className="about-para"),
                    html.Ul(
                        [html.Li(q) for q in CHIP_PROMPTS]
                        + [
                            html.Li("노원구에서 최근 전세 거래된 아파트 상위 10개"),
                            html.Li("서울에서 단위면적가가 가장 높은 자치구 TOP 5"),
                            html.Li("분당구 재건축 관련 최근 뉴스 요약"),
                        ],
                        className="about-ul",
                    ),
                ],
            ),
            html.Div(
                className="about-tip",
                children=[
                    _fa("circle-info"),
                    html.Span(
                        " 처리 중에는 오른쪽 빨간 중단(⏹) 버튼으로 언제든 질의를 취소할 수 있습니다."
                    ),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 섹션 6. PDF RAG 활용법
# ---------------------------------------------------------------------------


def _section_rag() -> html.Section:
    steps = [
        ("1", "채팅 패널 열기", "우하단 AI 아이콘 클릭"),
        ("2", "PDF 업로드", "📎 버튼 → .pdf 파일 선택 (50MB 이하)"),
        ("3", "자동 처리", "파싱 → 청킹 → 임베딩 (10~30초 소요)"),
        ("4", "질문", "업로드 후 문서 내용 자연어 질의"),
    ]
    return html.Section(
        className="about-section",
        children=[
            html.H2("PDF 문서 RAG"),
            html.P(
                "분석 리포트·정책 문서를 업로드하면 내용 기반 질의응답이 가능합니다. "
                "DB 질의와 문서 질의가 자연스럽게 결합됩니다.",
                className="about-para",
            ),
            html.Ol(
                [
                    html.Li(
                        [
                            html.Span(n, className="step-n"),
                            html.B(title),
                            html.Span(desc, className="step-desc"),
                        ]
                    )
                    for n, title, desc in steps
                ],
                className="about-steps",
            ),
            html.Div(
                className="about-tip",
                children=[
                    _fa("circle-info"),
                    html.Span(
                        " 지원 형식: PDF 1종. 업로드 이력은 🗂 목록 버튼에서 확인할 수 있습니다."
                    ),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 섹션 7. 기술 스택
# ---------------------------------------------------------------------------


def _section_stack() -> html.Section:
    stack = [
        ("Python 3.13 + uv", "언어·패키지 매니저"),
        ("PostgreSQL 18 + pgvector", "관계형 + 벡터 DB"),
        ("Plotly Dash 4 · dash-leaflet · dash-ag-grid", "UI 프레임워크"),
        ("LangChain 1.x · LangGraph 1.x", "에이전트 오케스트레이션"),
        ("Gemini 3.1 Flash-Lite", "LLM · 임베딩"),
        ("PyMuPDF", "PDF 파싱"),
        ("Dokploy · Docker Swarm", "배포 (Hostinger VPS)"),
    ]
    return html.Section(
        className="about-section",
        children=[
            html.H2("기술 스택"),
            html.Ul(
                [
                    html.Li([html.B(name), html.Span(f" — {desc}")])
                    for name, desc in stack
                ],
                className="about-ul",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 섹션 8. 버전·문의
# ---------------------------------------------------------------------------


def _section_version() -> html.Section:
    return html.Section(
        className="about-section about-footer",
        children=[
            html.Div(
                className="about-ver",
                children=[html.B("APT Insight"), " · version 0.1.0"],
            ),
            html.P(
                "교재 『공공데이터 활용 with AI』 advance 원료. "
                "문의·이슈는 프로젝트 저장소에 등록해 주세요.",
                className="about-muted",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


layout = html.Main(
    className="fd-main about-main",
    children=[
        html.Div(
            className="about-wrap",
            children=[
                _section_hero(),
                _section_features(),
                _section_data_sources(),
                _section_glossary(),
                _section_chat(),
                _section_rag(),
                _section_stack(),
                _section_version(),
            ],
        ),
    ],
)
