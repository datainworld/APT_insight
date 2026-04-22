"""플로팅 채팅 패널 레이아웃 — 4단계 크기 전환 지원 (스펙 6장).

크기 상태는 `chat-size-mode` store 값에 따라 `data-size` 속성으로 CSS 에 반영된다.
- minimized: 56×56 아이콘 (FAB 역할 흡수) — 클릭 시 → compact
- compact: 400×min(640, 100vh-48) 기본 열린 상태
- expanded: clamp(480, 50vw, 800)×(100vh-24) 우측 도크
- maximized: 거의 전체 화면 오버레이

헤더 컨트롤 3개:
- [−] 최소화 (minimized)
- [⇲/⇱] 한 단계 크게/작게 (현재 모드에 따라 아이콘 변함 — CSS/JS 처리)
- [X] 닫기 = 최소화
"""

from __future__ import annotations

from dash import dcc, html

from dash_app.config import CHIP_PROMPTS


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


def chat_components() -> list:
    """루트 레이아웃에 mount 되는 채팅 패널 전체.

    Section 하나로 4단계를 모두 표현하며 `data-size` 로 상태를 드러낸다.
    minimized 상태에서는 내부 UI 가 감춰지고 아이콘만 클릭 타깃으로 노출된다.
    """
    return [
        html.Section(
            id="chat-panel",
            className="chat-panel",
            **{"data-size": "minimized"},  # type: ignore[arg-type]
            children=[
                # minimized 상태에서 전체 섹션을 클릭 타겟으로 만드는 오버레이.
                # compact+ 상태에서는 `pointer-events: none` 으로 비활성.
                html.Button(
                    [
                        html.Span(className="pulse"),
                        _fa("comment-dots"),
                        html.Span("AI 채팅", className="chat-open-label"),
                    ],
                    id="chat-open",
                    className="chat-open-btn",
                    n_clicks=0,
                    title="AI 어시스턴트 열기",
                ),
                # 헤더 (compact+ 에서 표시)
                html.Header(
                    className="chat-hdr",
                    children=[
                        html.Div(className="avatar", children=_fa("robot")),
                        html.Div(
                            className="title",
                            children=[
                                "APT Insight 도우미",
                                html.Em(
                                    children=[
                                        html.Span(className="dot-live"),
                                        "실시간 · DB 전체",
                                    ],
                                ),
                            ],
                        ),
                        # 4단계 직접 선택 — 각 버튼이 해당 크기로 즉시 이동
                        html.Button(
                            _fa("window-minimize"),
                            id={"role": "chat-size", "mode": "minimized"},
                            className="hdr-btn",
                            title="최소화",
                            n_clicks=0,
                        ),
                        html.Button(
                            _fa("window-restore"),
                            id={"role": "chat-size", "mode": "compact"},
                            className="hdr-btn",
                            title="컴팩트",
                            n_clicks=0,
                        ),
                        html.Button(
                            _fa("window-maximize"),
                            id={"role": "chat-size", "mode": "expanded"},
                            className="hdr-btn",
                            title="확장 (우측 도크)",
                            n_clicks=0,
                        ),
                        html.Button(
                            _fa("expand"),
                            id={"role": "chat-size", "mode": "maximized"},
                            className="hdr-btn",
                            title="최대화",
                            n_clicks=0,
                        ),
                    ],
                ),
                # 퀵 액션 바 — PDF 업로드 + 업로드 목록 토글
                html.Div(
                    className="chat-quick",
                    children=[
                        dcc.Upload(
                            id="chat-upload",
                            children=html.Span(
                                [_fa("paperclip"), " PDF 업로드"],
                                className="upload-inner",
                            ),
                            className="quick-btn upload-btn",
                            multiple=False,
                            accept=".pdf",
                            max_size=50 * 1024 * 1024,
                        ),
                        html.Button(
                            [
                                _fa("folder-open"),
                                html.Span(id="chat-upload-count", children=" 목록 (0)"),
                            ],
                            id="chat-btn-uploads",
                            className="quick-btn",
                            n_clicks=0,
                            title="업로드한 PDF 목록",
                        ),
                    ],
                ),
                # 업로드 상태 라인 (진행/완료 텍스트 1줄)
                html.Div(
                    id="chat-upload-status",
                    className="chat-upload-status",
                    children="",
                ),
                # 업로드 목록 drawer (열림/닫힘은 className 토글)
                html.Div(
                    id="chat-uploads-drawer",
                    className="uploads-drawer hidden",
                    children=[
                        html.Div(
                            className="drawer-head",
                            children=[
                                html.B("업로드한 PDF"),
                                html.Button(
                                    _fa("xmark"),
                                    id="chat-drawer-close",
                                    className="hdr-btn",
                                    n_clicks=0,
                                ),
                            ],
                        ),
                        html.Div(
                            id="chat-uploads-list",
                            className="drawer-body",
                            children=[],
                        ),
                    ],
                ),
                # 메시지 스크롤 영역
                html.Div(
                    id="chat-scroll",
                    className="chat-scroll",
                    children=[welcome_msg()],
                ),
                # 입력 (+ 중단 버튼 — busy 상태일 때만 표시)
                html.Div(
                    className="chat-input",
                    children=[
                        html.Div(
                            className="wrap",
                            children=[
                                dcc.Textarea(
                                    id="chat-input",
                                    placeholder="자연어로 질문하세요",
                                    rows=1,
                                ),
                                html.Button(
                                    _fa("stop"),
                                    id="chat-cancel",
                                    className="btn-s btn-cancel",
                                    n_clicks=0,
                                    title="질의 중단",
                                    style={"display": "none"},
                                ),
                                html.Button(
                                    _fa("paper-plane"),
                                    id="chat-send",
                                    className="btn-s",
                                    n_clicks=0,
                                ),
                            ],
                        ),
                    ],
                ),
                # 기존 메시지 기능 stores (Phase D.3 에서 chat-history 로 마이그레이션)
                dcc.Store(id="chat-msgs", data=[{"role": "sys", "kind": "welcome"}]),
                dcc.Store(id="chat-thread", storage_type="session"),
                dcc.Store(id="chat-busy", data=False),
                # ESC 키 이벤트 카운터 — clientside 에서 증가시키면 size-transition 콜백이 감지
                dcc.Store(id="chat-esc-trigger", data=0),
            ],
        ),
    ]


def welcome_msg() -> html.Div:
    return html.Div(
        className="c-msg sys",
        children=[
            html.Div(className="av", children=_fa("robot")),
            html.Div(
                children=[
                    html.Div(
                        className="bub",
                        children=[
                            "안녕하세요! ",
                            html.Strong("APT Insight 도우미"),
                            " 입니다. 수도권 아파트 거래 · 호가 · 전세 지표를 질문하시거나, "
                            "아래 칩을 눌러 예시 질의를 사용해 보세요.",
                        ],
                    ),
                    html.Div(
                        className="c-chips",
                        children=[
                            html.Button(
                                p,
                                id={"role": "chat-chip", "value": p},
                                className="c-chip",
                                n_clicks=0,
                            )
                            for p in CHIP_PROMPTS
                        ],
                    ),
                ],
            ),
        ],
    )
