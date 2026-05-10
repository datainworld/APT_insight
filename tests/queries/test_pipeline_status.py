"""data/reports/ 기반 last_refresh_timestamp / is_stale 단위 테스트."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dash_app.queries import pipeline_status


def test_returns_latest_date_among_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-04-15.json").write_text("{}", encoding="utf-8")
    (tmp_path / "2026-05-09.json").write_text("{}", encoding="utf-8")
    (tmp_path / "2026-04-21.json").write_text("{}", encoding="utf-8")

    assert pipeline_status.last_refresh_timestamp() == date(2026, 5, 9)


def test_returns_none_when_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path / "missing")

    assert pipeline_status.last_refresh_timestamp() is None


def test_returns_none_when_dir_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)

    assert pipeline_status.last_refresh_timestamp() is None


def test_ignores_invalid_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-05-09.json").write_text("{}", encoding="utf-8")
    (tmp_path / "junk.json").write_text("{}", encoding="utf-8")
    (tmp_path / "2026-13-99.json").write_text("{}", encoding="utf-8")

    assert pipeline_status.last_refresh_timestamp() == date(2026, 5, 9)


def test_is_stale_when_none_returns_true() -> None:
    assert pipeline_status.is_stale(None) is True


def test_is_stale_today_is_false() -> None:
    today = date(2026, 5, 10)
    assert pipeline_status.is_stale(today, today=today) is False


def test_is_stale_yesterday_within_default_threshold() -> None:
    today = date(2026, 5, 10)
    yesterday = date(2026, 5, 9)

    assert pipeline_status.is_stale(yesterday, today=today) is False


def test_is_stale_two_days_old_exceeds_default_threshold() -> None:
    today = date(2026, 5, 10)
    two_days_ago = date(2026, 5, 8)

    assert pipeline_status.is_stale(two_days_ago, today=today) is True


def test_is_stale_custom_threshold() -> None:
    today = date(2026, 5, 10)
    three_days_ago = date(2026, 5, 7)

    assert pipeline_status.is_stale(three_days_ago, today=today, threshold_days=3) is False
    assert pipeline_status.is_stale(three_days_ago, today=today, threshold_days=2) is True


def test_read_report_returns_dict_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-05-10.json").write_text(
        '{"date":"2026-05-10","status":"success"}', encoding="utf-8"
    )

    report = pipeline_status.read_report(date(2026, 5, 10))
    assert report == {"date": "2026-05-10", "status": "success"}


def test_read_report_returns_none_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)

    assert pipeline_status.read_report(date(2026, 5, 10)) is None


def test_read_report_returns_none_on_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-05-10.json").write_text("not-json", encoding="utf-8")

    assert pipeline_status.read_report(date(2026, 5, 10)) is None


def test_recent_reports_returns_oldest_to_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)
    today = date(2026, 5, 10)
    (tmp_path / "2026-05-08.json").write_text('{"status":"success"}', encoding="utf-8")
    (tmp_path / "2026-05-10.json").write_text('{"status":"error"}', encoding="utf-8")

    history = pipeline_status.recent_reports(days=3, today=today)

    assert [d for d, _ in history] == [date(2026, 5, 8), date(2026, 5, 9), date(2026, 5, 10)]
    assert history[0][1] == {"status": "success"}
    assert history[1][1] is None  # 2026-05-09 is missing
    assert history[2][1] == {"status": "error"}


def test_recent_reports_default_14_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_status, "REPORTS_DIR", tmp_path)

    history = pipeline_status.recent_reports(today=date(2026, 5, 10))

    assert len(history) == 14
    assert all(r is None for _, r in history)
