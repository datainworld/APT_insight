"""사이드바 '마지막 갱신' 상태 콜백 — 페이지 이동 시마다 갱신.

dash_app/queries/pipeline_status.py 를 단일 소스로 사용한다.
리포트가 stale 이거나 누락되면 경고 아이콘을 노출하고 서버 로그에 기록한다.
"""

from __future__ import annotations

import logging
from datetime import date

from dash import Input, Output, callback

from dash_app.queries.pipeline_status import is_stale, last_refresh_timestamp

logger = logging.getLogger(__name__)

_ICON_HIDDEN = {
    "display": "none",
    "color": "var(--warn, #ff9800)",
    "marginLeft": "6px",
}
_ICON_SHOWN = {**_ICON_HIDDEN, "display": "inline"}


@callback(
    Output("sidebar-last-refresh-text", "children"),
    Output("sidebar-last-refresh-warning", "style"),
    Output("sidebar-last-refresh-warning", "title"),
    Input("_url", "pathname"),
)
def _update_last_refresh(_pathname: str | None) -> tuple[str, dict, str]:
    latest = last_refresh_timestamp()
    today = date.today()
    stale = is_stale(latest, today=today)

    if latest is None:
        text = "—"
        tooltip = "data/reports/ 에 리포트 파일이 없습니다 — 파이프라인이 실행되지 않았을 수 있습니다."
        logger.warning("sidebar last_refresh: no report files found in data/reports/")
    else:
        text = latest.strftime("%Y-%m-%d")
        if stale:
            days_old = (today - latest).days
            tooltip = (
                f"마지막 리포트가 {days_old}일 전 생성됨 — 파이프라인 실행 상태를 확인해 주세요."
            )
            logger.warning(
                "sidebar last_refresh: stale by %d days (latest=%s)", days_old, latest
            )
        else:
            tooltip = ""

    return text, (_ICON_SHOWN if stale else _ICON_HIDDEN), tooltip
