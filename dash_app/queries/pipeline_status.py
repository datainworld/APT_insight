"""파이프라인 실행 상태 조회 — data/reports/ 파일시스템 기반.

Dash 사이드바의 "마지막 갱신" 표시 + /about 페이지의 데이터 업데이트 현황 섹션이
이 모듈을 단일 신뢰 소스로 사용한다. data/reports/{YYYY-MM-DD}.json 은
pipeline/run_daily.py 가 매일 03:00 KST 실행 후 저장하는 일일 리포트 파일이다.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from shared.config import BASE_DIR

logger = logging.getLogger(__name__)

REPORTS_DIR: Path = BASE_DIR / "data" / "reports"

# 어제까지는 정상 — run_daily.py 는 03:00 KST 에 실행되므로
# 사용자가 자정 직후 ~ 03:00 사이에 접속하면 가장 최근 리포트는 어제 날짜다.
STALE_THRESHOLD_DAYS = 1

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def last_refresh_timestamp() -> date | None:
    """data/reports/{YYYY-MM-DD}.json 중 가장 최근 날짜 반환. 없으면 None."""
    if not REPORTS_DIR.exists():
        return None

    dates: list[date] = []
    for f in REPORTS_DIR.glob("*.json"):
        m = _DATE_RE.match(f.name)
        if not m:
            continue
        try:
            dates.append(date.fromisoformat(m.group(1)))
        except ValueError:
            continue

    return max(dates) if dates else None


def is_stale(
    latest: date | None,
    today: date | None = None,
    threshold_days: int = STALE_THRESHOLD_DAYS,
) -> bool:
    """리포트가 threshold_days 보다 오래되었거나 없으면 True."""
    if latest is None:
        return True
    today = today or date.today()
    return (today - latest).days > threshold_days


def read_report(d: date) -> dict[str, Any] | None:
    """해당 날짜의 리포트 JSON 을 dict 로 반환. 없거나 파싱 실패 시 None."""
    path = REPORTS_DIR / f"{d.isoformat()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("read_report: failed to read %s: %s", path, e)
        return None


def recent_reports(
    days: int = 14, today: date | None = None
) -> list[tuple[date, dict[str, Any] | None]]:
    """최근 N일치 (날짜, 리포트dict | None) 리스트. 오래된 → 최신 순.

    파일이 없는 날은 None 으로 채워서 누락된 날을 시각적으로 구분할 수 있게 한다.
    """
    today = today or date.today()
    return [
        (today - timedelta(days=i), read_report(today - timedelta(days=i)))
        for i in range(days - 1, -1, -1)
    ]
