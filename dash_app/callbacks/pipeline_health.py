"""/about 페이지의 데이터 업데이트 현황 섹션 콜백.

Input("_url", "pathname") 트리거 — 페이지 진입 시마다 파일시스템 재조회.
about-pipeline-section 이 layout 에 없는 경로(다른 페이지)에서는 Dash 가
suppress_callback_exceptions=True 설정으로 자동 무시한다.
"""

from __future__ import annotations

from datetime import date

from dash import Input, Output, callback

from dash_app.components.pipeline_health import render_pipeline_body
from dash_app.queries.pipeline_status import (
    last_refresh_timestamp,
    read_report,
    recent_reports,
)


@callback(
    Output("about-pipeline-body", "children"),
    Input("_url", "pathname"),
)
def _update_pipeline_body(_pathname: str | None) -> list:
    history = recent_reports(days=14, today=date.today())
    # 14일 윈도우 안의 최신 리포트 우선. 없으면 윈도우 밖의 가장 최신 리포트.
    latest = next((r for _, r in reversed(history) if r is not None), None)
    if latest is None:
        absolute_latest = last_refresh_timestamp()
        if absolute_latest is not None:
            latest = read_report(absolute_latest)
    return render_pipeline_body(latest, history)
