"""pipeline_health 컴포넌트 렌더링 테스트 — DB 불필요."""

from __future__ import annotations

from datetime import date

from dash_app.components.pipeline_health import (
    pipeline_health_section,
    render_pipeline_body,
)


def _flatten(node) -> list:
    """재귀적으로 자식 노드를 펼쳐서 리스트로 반환 (None 제외)."""
    out: list = []
    if node is None:
        return out
    if isinstance(node, str):
        out.append(node)
        return out
    if isinstance(node, list):
        for c in node:
            out.extend(_flatten(c))
        return out
    out.append(node)
    children = getattr(node, "children", None)
    if children is None:
        return out
    out.extend(_flatten(children))
    return out


def _all_strings(node) -> str:
    return " ".join(s for s in _flatten(node) if isinstance(s, str))


def test_section_has_required_ids() -> None:
    section = pipeline_health_section()
    flat = _flatten(section)
    ids = {getattr(n, "id", None) for n in flat if hasattr(n, "id")}

    assert "about-pipeline-section" in ids
    assert "about-pipeline-body" in ids


def test_render_with_complete_report() -> None:
    today = date(2026, 5, 10)
    latest = {
        "date": "2026-05-10",
        "status": "success",
        "finished_at": "2026-05-10T09:14:47+09:00",
        "elapsed_seconds": 8087,
        "rt": {"status": "success", "new_complexes": 6, "new_trades": 104, "new_rents": 34},
        "nv": {"status": "success", "new": 1610, "changed": 14, "kept": 640941, "closed": 1772},
        "news": {"status": "success", "inserted": 26, "skipped_duplicate": 0, "error_count": 0},
        "mv_refresh": {"status": "success", "refreshed": ["mv_a", "mv_b"], "error_count": 0},
    }
    history = [(today, latest)]

    body = render_pipeline_body(latest, history)
    text = _all_strings(body)

    assert "2026-05-10" in text
    assert "성공" in text  # status badge
    # 단계별 카운트가 포함되어야 함
    assert "104" in text  # new_trades
    assert "1,610" in text  # nv.new (천단위 콤마)
    assert "26" in text  # news inserted
    assert "2개" in text  # mv refreshed list count


def test_render_with_no_reports_shows_empty_message() -> None:
    history = [(date(2026, 5, 10), None)]

    body = render_pipeline_body(None, history)
    text = _all_strings(body)

    assert "리포트 파일이 없습니다" in text


def test_render_handles_partial_status() -> None:
    latest = {
        "date": "2026-05-10",
        "status": "partial",
        "finished_at": "2026-05-10T09:00:00",
        "elapsed_seconds": 600,
        "rt": {"status": "success", "new_trades": 50},
        "nv": {"status": "error", "message": "cookie expired"},
    }

    body = render_pipeline_body(latest, [(date(2026, 5, 10), latest)])
    flat = _flatten(body)

    badge_classes = [
        getattr(n, "className", "") for n in flat if hasattr(n, "className")
    ]
    badge_str = " ".join(badge_classes)
    assert "pipeline-badge-partial" in badge_str  # overall
    assert "pipeline-badge-success" in badge_str  # rt
    assert "pipeline-badge-error" in badge_str  # nv

    text = _all_strings(body)
    assert "cookie expired" in text  # error message expanded


def test_render_marks_missing_days_in_strip() -> None:
    today = date(2026, 5, 10)
    history = [
        (date(2026, 5, 8), {"status": "success"}),
        (date(2026, 5, 9), None),  # missing
        (today, {"status": "success"}),
    ]

    body = render_pipeline_body({"status": "success"}, history)
    flat = _flatten(body)

    day_classes = [
        getattr(n, "className", "")
        for n in flat
        if hasattr(n, "className") and isinstance(getattr(n, "className", ""), str)
        and "pipeline-day pipeline-day-" in getattr(n, "className", "")
    ]
    assert any("pipeline-day-missing" in c for c in day_classes)
    assert sum("pipeline-day-success" in c for c in day_classes) == 2
