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
    """수도권 시군구 경계 GeoJSON 을 1회 로드 후 메모리 재사용.

    로드 단계에서:
    1) GeometryCollection 을 Polygon/MultiPolygon 으로 정규화 (Leaflet 아티팩트 방지)
    2) 시군구명을 DB 와 호환되는 canonical 형태로 보정 (예: 남구→미추홀구, 공백 삽입)
    """
    raw = _load_raw()
    cleaned = _sanitize_polygons(raw)
    return _canonicalize_names(cleaned)


def _load_raw() -> dict:
    for path in _GEOJSON_CANDIDATES:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        f"metro_sgg.geojson not found in any of: {[str(p) for p in _GEOJSON_CANDIDATES]}"
    )


def _canonicalize_names(gj: dict) -> dict:
    """feature.properties.name 을 DB 와 매칭 가능한 형태로 고친 새 dict 반환."""
    from dash_app.geo_names import normalize_geo_name

    out_features = []
    for f in gj.get("features", []):
        props = dict(f.get("properties") or {})
        code = props.get("code", "")
        prefix = code[:2] if code else ""
        props["name"] = normalize_geo_name(props.get("name", ""), prefix)
        out_features.append({**f, "properties": props})
    return {"type": "FeatureCollection", "features": out_features}


def _sanitize_polygons(raw: dict) -> dict:
    """feature.geometry 를 Polygon / MultiPolygon 으로 정규화.

    GeometryCollection 내부에서 Polygon 만 추출하고, 여러 개면 MultiPolygon 으로 병합.
    다각형이 하나도 없는 feature 는 버린다.
    """
    clean_features = []
    for f in raw.get("features", []):
        g = f.get("geometry") or {}
        gtype = g.get("type")
        if gtype in ("Polygon", "MultiPolygon"):
            clean_features.append(f)
            continue
        if gtype == "GeometryCollection":
            polys = []
            for sub in g.get("geometries", []):
                sub_type = sub.get("type")
                if sub_type == "Polygon":
                    polys.append(sub["coordinates"])
                elif sub_type == "MultiPolygon":
                    polys.extend(sub["coordinates"])
            if not polys:
                continue
            new_geom: dict = (
                {"type": "Polygon", "coordinates": polys[0]}
                if len(polys) == 1
                else {"type": "MultiPolygon", "coordinates": polys}
            )
            clean_features.append({**f, "geometry": new_geom})
    return {"type": "FeatureCollection", "features": clean_features}
