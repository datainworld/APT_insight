"""다크 모드 토글 — Phase E 에서 확장 예정.

현재는 루트 body class만 제어하는 placeholder.
"""

from __future__ import annotations

from dash import Input, Output, clientside_callback

# Clientside — dcc.Store(id="theme") 의 값을 <body data-theme="..."> 로 반영
clientside_callback(
    """
    function(theme) {
        document.body.setAttribute('data-theme', theme || 'dark');
        return window.dash_clientside.no_update;
    }
    """,
    Output("theme", "data", allow_duplicate=True),
    Input("theme", "data"),
    prevent_initial_call="initial_duplicate",
)
