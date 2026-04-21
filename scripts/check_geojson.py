"""metro_sgg.geojson 의 feature 별 이상 여부 점검."""

from __future__ import annotations

from dash_app.db import load_metro_geojson


def main() -> None:
    gj = load_metro_geojson()
    features = gj["features"]
    print(f"Total features: {len(features)}")

    types: dict[str, int] = {}
    missing_coords: list[tuple[int, str, str]] = []
    empty_coords: list[tuple[int, str, str]] = []

    for i, f in enumerate(features):
        props = f.get("properties") or {}
        name = props.get("name", "")
        code = props.get("code", "")
        g = f.get("geometry") or {}
        gtype = g.get("type", "NONE")
        types[gtype] = types.get(gtype, 0) + 1
        if "coordinates" not in g:
            missing_coords.append((i, name, code))
            continue
        coords = g["coordinates"]
        if not coords:
            empty_coords.append((i, name, code))

    print(f"Geometry types: {types}")
    print(f"Missing coordinates: {len(missing_coords)}")
    for i, name, code in missing_coords[:10]:
        print(f"  f{i}: {name} ({code}) geometry={features[i].get('geometry')}")
    print(f"Empty coordinates: {len(empty_coords)}")
    for i, name, code in empty_coords[:10]:
        print(f"  f{i}: {name} ({code})")


if __name__ == "__main__":
    main()
