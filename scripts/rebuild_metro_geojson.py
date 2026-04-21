"""kostat 2013 municipalities-geo.json 에서 수도권(서울/경기/인천)만 추출.

출처: https://github.com/southkorea/southkorea-maps/blob/master/kostat/2013/json/skorea_municipalities_geo.json
이 파일은 kostat 원본이며, GeometryCollection 없이 깔끔한 Polygon/MultiPolygon 으로 구성.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_METRO_PREFIXES = ("11", "23", "31")  # 서울, 인천(2013 코드), 경기
_OUT = Path(__file__).resolve().parent.parent / "data" / "maps" / "metro_sgg.geojson"


def main(src: str) -> None:
    src_path = Path(src)
    if not src_path.exists():
        print(f"Source not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(src_path.read_text(encoding="utf-8"))
    metro = [
        f
        for f in raw["features"]
        if (f.get("properties", {}).get("code") or "").startswith(_METRO_PREFIXES)
    ]

    gtypes: dict[str, int] = {}
    for f in metro:
        t = f["geometry"]["type"]
        gtypes[t] = gtypes.get(t, 0) + 1

    out = {"type": "FeatureCollection", "features": metro}
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(metro)} features to {_OUT}")
    print(f"Geometry types: {gtypes}")
    print(f"Size: {_OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.rebuild_metro_geojson <source.json>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
