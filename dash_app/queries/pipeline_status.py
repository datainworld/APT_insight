"""파이프라인 실행 상태 조회 — data/reports/ 파일시스템 기반.

Dash 사이드바의 "마지막 갱신" 표시는 이 모듈을 단일 신뢰 소스로 사용한다.
data/reports/{YYYY-MM-DD}.json 은 pipeline/run_daily.py 가 매일 03:00 KST 실행 후
저장하는 일일 리포트 파일이다.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

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
