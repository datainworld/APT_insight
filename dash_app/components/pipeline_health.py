"""'데이터 업데이트 현황' 섹션 — /about 페이지에 임베드.

페이지 진입 시 콜백이 `data/reports/` 의 최신 리포트 + 최근 14일 status 추세를
읽어 채운다. 리포트 스키마는 pipeline/run_daily.py 의 report dict 와 일치해야 한다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from dash import html

# Stage 메타: 리포트 키 → (UI 라벨, 표시할 카운트 필드 + 한글 라벨)
_STAGES: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "rt",
        "RT (국토부)",
        [
            ("new_complexes", "새 단지"),
            ("new_trades", "새 매매"),
            ("new_rents", "새 전월세"),
        ],
    ),
    (
        "nv",
        "NV (네이버)",
        [
            ("new", "신규"),
            ("changed", "변경"),
            ("closed", "종료"),
        ],
    ),
    (
        "news",
        "News (뉴스)",
        [
            ("inserted", "신규"),
            ("skipped_duplicate", "중복"),
            ("error_count", "에러"),
        ],
    ),
    (
        "mv_refresh",
        "MV (집계뷰)",
        [
            ("refreshed", "갱신 view"),
            ("error_count", "에러"),
        ],
    ),
]

_STATUS_LABELS = {"success": "성공", "partial": "부분 실패", "error": "실패"}


def pipeline_health_section() -> html.Section:
    """정적 컨테이너 — 콜백이 children 을 채운다."""
    return html.Section(
        id="about-pipeline-section",
        className="about-section",
        children=[
            html.H2("데이터 업데이트 현황"),
            html.P(
                "매일 03:00 KST 일일 파이프라인(`pipeline/run_daily.py`) 실행 결과. "
                "리포트는 `data/reports/{날짜}.json` 에 저장됩니다.",
                className="about-para",
            ),
            html.Div(id="about-pipeline-body", children="—"),
        ],
    )


# ---------------------------------------------------------------------------
# Render helpers (콜백에서 호출)
# ---------------------------------------------------------------------------


def _badge(status: str | None) -> html.Span:
    label = _STATUS_LABELS.get(status or "", "데이터 없음")
    cls = f"pipeline-badge pipeline-badge-{status or 'missing'}"
    return html.Span(label, className=cls)


def _format_elapsed(seconds: float | int | None) -> str:
    if not seconds:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h:
        return f"{h}시간 {m}분 {ss}초"
    if m:
        return f"{m}분 {ss}초"
    return f"{ss}초"


def _format_finished(iso_ts: str | None) -> str:
    if not iso_ts:
        return "—"
    try:
        return datetime.fromisoformat(iso_ts).strftime("%H:%M:%S")
    except ValueError:
        return iso_ts


def _stage_count(stage_data: dict[str, Any], field: str) -> str:
    val = stage_data.get(field)
    if val is None:
        return "—"
    if isinstance(val, list):
        return f"{len(val)}개"
    return f"{val:,}" if isinstance(val, int) else str(val)


def _stage_card(key: str, label: str, fields: list[tuple[str, str]],
                stage_data: dict[str, Any] | None) -> html.Div:
    if stage_data is None:
        return html.Div(
            className="pipeline-stage",
            children=[
                html.Div(label, className="pipeline-stage-name"),
                _badge(None),
                html.Div("리포트에 없음", className="pipeline-stage-note"),
            ],
        )
    return html.Div(
        className="pipeline-stage",
        children=[
            html.Div(label, className="pipeline-stage-name"),
            _badge(stage_data.get("status")),
            html.Ul(
                [
                    html.Li(
                        [
                            html.Span(lbl, className="pipeline-stage-l"),
                            html.Span(_stage_count(stage_data, fld),
                                      className="pipeline-stage-v"),
                        ]
                    )
                    for fld, lbl in fields
                ],
                className="pipeline-stage-list",
            ),
        ],
    )


def _day_strip(history: list[tuple[date, dict[str, Any] | None]]) -> html.Div:
    days = []
    for d, report in history:
        status = (report or {}).get("status") if report else None
        cls = f"pipeline-day pipeline-day-{status or 'missing'}"
        title = f"{d.isoformat()} · {_STATUS_LABELS.get(status or '', '리포트 없음')}"
        days.append(html.Div(d.strftime("%d"), className=cls, title=title))
    return html.Div(
        className="pipeline-day-strip",
        children=[
            html.Div("최근 14일", className="pipeline-day-label"),
            html.Div(days, className="pipeline-day-row"),
        ],
    )


def _error_messages(report: dict[str, Any]) -> html.Details | None:
    """단계별 message 필드가 있으면 펼치기 토글로 노출."""
    msgs: list[tuple[str, str]] = []
    for key, label, _ in _STAGES:
        stage = report.get(key)
        if isinstance(stage, dict) and stage.get("message"):
            msgs.append((label, str(stage["message"])))
    if not msgs:
        return None
    return html.Details(
        className="pipeline-errors",
        children=[
            html.Summary([html.I(className="fa-solid fa-circle-exclamation"),
                          " 에러 메시지 보기"]),
            *[html.Div([html.B(label + ": "), html.Code(msg)],
                       className="pipeline-error-row")
              for label, msg in msgs],
        ],
    )


def render_pipeline_body(
    latest: dict[str, Any] | None,
    history: list[tuple[date, dict[str, Any] | None]],
) -> list:
    """콜백에서 호출 — about-pipeline-body 의 children 을 만든다."""
    if latest is None:
        return [
            html.Div(
                "리포트 파일이 없습니다 — 일일 파이프라인이 실행되지 않았을 수 있습니다.",
                className="pipeline-empty",
            ),
            _day_strip(history),
        ]

    finished = _format_finished(latest.get("finished_at"))
    elapsed = _format_elapsed(latest.get("elapsed_seconds"))

    return [
        # Overall status row
        html.Div(
            className="pipeline-overall",
            children=[
                html.Div(latest.get("date", "—"), className="pipeline-overall-date"),
                _badge(latest.get("status")),
                html.Div(
                    [
                        html.Span("완료 "), html.B(finished),
                        html.Span(" · 소요 "), html.B(elapsed),
                    ],
                    className="pipeline-overall-meta",
                ),
            ],
        ),
        # 4 stage cards
        html.Div(
            className="pipeline-stages",
            children=[
                _stage_card(key, label, fields, latest.get(key))
                for key, label, fields in _STAGES
            ],
        ),
        # 14-day history
        _day_strip(history),
        # Error details (optional)
        _error_messages(latest),
    ]
