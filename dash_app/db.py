"""Pooled SQLAlchemy engine for the Dash web tier.

Dash callbacks fire in parallel; the default `shared.db.get_engine()` creates
a fresh engine per call with no pool. This module owns a singleton engine
sized for web traffic, with a statement_timeout that kills runaway queries
(a stale pool connection can't keep a backend looping for hours).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from shared.config import DATABASE_URL

_engine: Engine | None = None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GEOJSON_CANDIDATES = (
    _PROJECT_ROOT / "data" / "maps" / "metro_sgg.geojson",
    _PROJECT_ROOT / "assets" / "maps" / "metro_sgg.geojson",  # Docker layout
)


def get_engine() -> Engine:
    """Pooled engine singleton — dash_app 내부에서는 이 함수만 사용한다."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            pool_size=20,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"options": "-c statement_timeout=60000"},
        )
    return _engine


@lru_cache(maxsize=1)
def load_metro_geojson() -> dict:
    """수도권 77개 시군구 경계 GeoJSON을 1회 로드 후 메모리 재사용."""
    for path in _GEOJSON_CANDIDATES:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        f"metro_sgg.geojson not found in any of: {[str(p) for p in _GEOJSON_CANDIDATES]}"
    )
