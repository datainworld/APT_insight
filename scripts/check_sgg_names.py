"""GeoJSON 시군구명 vs DB(rt_complex) 시군구명 대조."""

from __future__ import annotations

from sqlalchemy import bindparam, text

from dash_app.db import get_engine, load_metro_geojson


_SIDO_PREFIX = {"서울특별시": "11", "인천광역시": "23", "경기도": "31"}


def _geo_sggs() -> dict[str, set[str]]:
    gj = load_metro_geojson()
    out: dict[str, set[str]] = {s: set() for s in _SIDO_PREFIX}
    for f in gj["features"]:
        code = (f.get("properties") or {}).get("code", "")
        name = (f.get("properties") or {}).get("name", "")
        for sido, prefix in _SIDO_PREFIX.items():
            if code.startswith(prefix):
                out[sido].add(name)
                break
    return out


def _db_sggs() -> dict[str, set[str]]:
    sql = text("""
        SELECT DISTINCT sido_name, sgg_name
        FROM rt_complex
        WHERE sido_name IN :sidos AND sgg_name IS NOT NULL
    """).bindparams(bindparam("sidos", expanding=True))
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"sidos": list(_SIDO_PREFIX)}).fetchall()
    out: dict[str, set[str]] = {s: set() for s in _SIDO_PREFIX}
    for sido, sgg in rows:
        if sido in out:
            out[sido].add(sgg)
    return out


def main() -> None:
    geo = _geo_sggs()
    db = _db_sggs()

    for sido in _SIDO_PREFIX:
        g, d = geo[sido], db[sido]
        only_geo = sorted(g - d)
        only_db = sorted(d - g)
        both = sorted(g & d)
        print(f"\n== {sido} ==")
        print(f"  geo={len(g)} db={len(d)} 교집합={len(both)}")
        if only_geo:
            print(f"  [지도만 있음] ({len(only_geo)}): {only_geo}")
        if only_db:
            print(f"  [DB만 있음]   ({len(only_db)}): {only_db}")


if __name__ == "__main__":
    main()
