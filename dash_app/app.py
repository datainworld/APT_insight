"""Plotly Dash 멀티페이지 엔트리 — APT Insight."""

from __future__ import annotations

import os

import dash
from dash import Dash, dcc, html

# Global callbacks (register via side effect)
from dash_app.callbacks import navigation as _nav  # noqa: F401
from dash_app.callbacks import theme as _theme  # noqa: F401
from dash_app.components.chat_panel import callbacks as _chat_cb  # noqa: F401
from dash_app.components.chat_panel.layout import chat_components
from dash_app.components.sidebar import sidebar
from dash_app.queries.rt_queries import last_refresh_timestamp

FONT_AWESOME = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"


def _root_stores() -> list[dcc.Store]:
    """Phase B 기준 — 채팅 4단계 크기 전환 store 는 Phase D 에서 연결."""
    return [
        dcc.Store(id="theme", storage_type="local", data="dark"),
        dcc.Store(id="user-prefs", storage_type="local", data={}),
        dcc.Store(id="chat-size-mode", storage_type="session", data="minimized"),
        dcc.Store(id="chat-prev-size", storage_type="session", data="compact"),
        dcc.Store(id="chat-history", storage_type="session", data=[]),
        dcc.Store(id="chat-context", storage_type="memory", data={"page": "home"}),
        dcc.Store(id="chat-stream-buffer", storage_type="memory", data=""),
        dcc.Store(id="chat-upload-history", storage_type="session", data=[]),
    ]


def create_app() -> Dash:
    try:
        last_refresh = last_refresh_timestamp()
    except Exception:
        last_refresh = None

    app = Dash(
        __name__,
        use_pages=True,
        pages_folder="pages",
        external_stylesheets=[FONT_AWESOME],
        suppress_callback_exceptions=True,
        prevent_initial_callbacks="initial_duplicate",  # type: ignore[arg-type]
        title="APT Insight — 대시보드",
    )

    app.layout = html.Div(
        className="fd-shell dark-theme",
        children=[
            dcc.Location(id="_url", refresh=False),
            sidebar(last_refresh=last_refresh),
            dash.page_container,
            *chat_components(),
            *_root_stores(),
        ],
    )

    return app


app = create_app()
server = app.server


if __name__ == "__main__":
    host = os.environ.get("DASH_HOST", "0.0.0.0")
    port = int(os.environ.get("DASH_PORT", "8050"))
    debug = os.environ.get("DASH_DEBUG", "").lower() in ("1", "true")
    app.run(host=host, port=port, debug=debug)
