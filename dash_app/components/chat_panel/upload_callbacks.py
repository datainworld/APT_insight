"""PDF 업로드 채팅 콜백 — dcc.Upload → ingest_pdf → chat message + history.

진행 UX: 업로드 → 처리 중 상태 텍스트 → 완료 시 채팅 메시지 append.
background=True 로 긴 임베딩 작업을 비동기 처리하며 send 버튼과 함께 잠금.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from dash import Input, Output, State, callback, html
from dash.exceptions import PreventUpdate

from pipeline.ingest_pdf import ingest_pdf

_UPLOAD_DIR = Path("uploads")
_MAX_BYTES = 50 * 1024 * 1024


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


def _append_sys_answer(msgs: list, text: str) -> list:
    msgs = list(msgs or [])
    msgs.append({"role": "sys", "kind": "answer", "text": text})
    return msgs


def _safe_filename(name: str) -> str:
    name = re.sub(r"[/\\]+", "_", name or "file.pdf")
    name = re.sub(r"[^a-zA-Z0-9가-힣._-]", "_", name)
    return name or "file.pdf"


@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-upload-history", "data", allow_duplicate=True),
    Output("chat-upload-count", "children"),
    Output("chat-upload-status", "children"),
    Output("chat-upload", "contents"),
    Input("chat-upload", "contents"),
    State("chat-upload", "filename"),
    State("chat-msgs", "data"),
    State("chat-upload-history", "data"),
    background=True,
    running=[
        (Output("chat-upload", "disable_click"), True, False),
        (Output("chat-upload-status", "children"), "처리 중… (파싱 · 임베딩)", ""),
    ],
    prevent_initial_call=True,
)
def _on_upload(contents: str | None, filename: str | None, msgs: list, history: list):
    if not contents:
        raise PreventUpdate

    safe = _safe_filename(filename or "uploaded.pdf")

    try:
        _, data = contents.split(",", 1)
        file_bytes = base64.b64decode(data)
    except Exception as e:
        return (
            _append_sys_answer(msgs, f"업로드 실패 — 디코딩 오류: {e}"),
            history or [],
            f" 목록 ({len(history or [])})",
            "",
            None,
        )

    if len(file_bytes) > _MAX_BYTES:
        return (
            _append_sys_answer(msgs, f"파일이 너무 큽니다 (최대 {_MAX_BYTES // 1024 // 1024}MB). 현재: {len(file_bytes) // 1024 // 1024}MB"),
            history or [],
            f" 목록 ({len(history or [])})",
            "",
            None,
        )

    if not file_bytes.startswith(b"%PDF"):
        return (
            _append_sys_answer(msgs, "PDF 파일이 아닙니다 (매직 바이트 `%PDF` 불일치)."),
            history or [],
            f" 목록 ({len(history or [])})",
            "",
            None,
        )

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = _UPLOAD_DIR / safe
    target.write_bytes(file_bytes)

    try:
        result = ingest_pdf(target, source_name=safe)
    except Exception as e:
        return (
            _append_sys_answer(msgs, f"적재 실패: {e}"),
            history or [],
            f" 목록 ({len(history or [])})",
            "",
            None,
        )

    new_history = list(history or []) + [
        {
            "filename": safe,
            "uploaded_at": result.uploaded_at,
            "pages": result.pages,
            "chunks": result.chunks,
        }
    ]
    msg = (
        f"**PDF '{safe}' 등록 완료** ({result.pages}페이지 · {result.chunks}개 청크). "
        "이제 이 문서의 내용을 질문하실 수 있습니다."
    )
    return (
        _append_sys_answer(msgs, msg),
        new_history,
        f" 목록 ({len(new_history)})",
        "",
        None,
    )


# --- 업로드 목록 drawer toggle + 목록 렌더 ---
@callback(
    Output("chat-uploads-drawer", "className"),
    Input("chat-btn-uploads", "n_clicks"),
    Input("chat-drawer-close", "n_clicks"),
    State("chat-uploads-drawer", "className"),
    prevent_initial_call=True,
)
def _toggle_drawer(open_clicks, close_clicks, cur_class):
    from dash import ctx

    trig = ctx.triggered_id
    base = "uploads-drawer"
    if trig == "chat-drawer-close":
        return f"{base} hidden"
    if trig == "chat-btn-uploads":
        if cur_class and "hidden" not in cur_class:
            return f"{base} hidden"
        return base
    raise PreventUpdate


@callback(
    Output("chat-uploads-list", "children"),
    Input("chat-upload-history", "data"),
)
def _render_upload_list(history: list[dict[str, Any]] | None) -> list:
    if not history:
        return [
            html.Div(
                "업로드한 PDF 가 없습니다",
                className="drawer-empty",
            )
        ]
    out: list = []
    # 최신 우선
    for item in reversed(history):
        uploaded = (item.get("uploaded_at") or "").replace("T", " ").rsplit("+", 1)[0]
        out.append(
            html.Div(
                className="upload-row",
                children=[
                    html.Div(
                        _fa("file-pdf"),
                        className="upload-icon",
                    ),
                    html.Div(
                        className="upload-meta",
                        children=[
                            html.Div(item.get("filename", "—"), className="upload-name"),
                            html.Div(
                                f"{item.get('pages', '?')}p · {item.get('chunks', '?')} 청크 · {uploaded}",
                                className="upload-sub",
                            ),
                        ],
                    ),
                ],
            )
        )
    return out
