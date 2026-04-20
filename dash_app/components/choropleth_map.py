"""dash-leaflet 기반 시군구 choropleth — Phase C 지도 컴포넌트.

GeoJSON 은 서버 기동 시 한 번 로드 후 재사용 (dash_app.db.load_metro_geojson).
각 feature 의 `properties.fillColor` 에 Python 에서 미리 색을 주입하고,
클라이언트 style 함수가 해당 색을 읽어 렌더한다.
"""

from __future__ import annotations

import copy
from typing import Literal

import dash_leaflet as dl
from dash import html
from dash_extensions.javascript import assign

from dash_app.db import load_metro_geojson

ColorScale = Literal["Blues", "Oranges", "Greens", "Reds"]

# 밝은 → 진한 8단계 램프. HTML/CSS 디자인 토큰 기반 (darkmatter 타일과 호환)
_COLOR_RAMPS: dict[ColorScale, list[str]] = {
    "Blues": [
        "#cfe8ff", "#a9d2ff", "#80b8ff", "#5a9cfe",
        "#3c80eb", "#2c62c2", "#1f4b9a", "#153670",
    ],
    "Oranges": [
        "#fde7d4", "#fbcfa7", "#f7b377", "#ee9149",
        "#d96f2c", "#b0511f", "#82390f", "#56250a",
    ],
    "Greens": [
        "#d7f2df", "#b4e4c1", "#8cd1a2", "#5cb87f",
        "#3d9a5f", "#2a7746", "#1c5732", "#123c23",
    ],
    "Reds": [
        "#fde7e4", "#fbc9c0", "#f7a391", "#ef7f6d",
        "#d9584a", "#b0352c", "#81211d", "#651918",
    ],
}

_SIDO_PREFIX = {"서울특별시": "11", "인천광역시": "28", "경기도": "31"}
_SIDO_VIEW = {
    "서울특별시": (37.5665, 126.9780, 10),
    "경기도":    (37.4138, 127.5183, 8),
    "인천광역시": (37.4563, 126.7052, 10),
}

# Client-side style function — reads color + selected flag from feature.properties
_STYLE_HANDLE = assign("""function(feature, context){
    const p = feature.properties || {};
    const selected = p.selected === true;
    return {
        fillColor: p.fillColor || '#333',
        weight: selected ? 2.2 : 0.6,
        color: selected ? '#00f2fe' : '#1e1e1e',
        fillOpacity: 0.85,
        opacity: 1,
        dashArray: ''
    };
}""")


def _pick_bucket(value: float, vmin: float, vmax: float, n_buckets: int) -> int:
    if vmax <= vmin:
        return 0
    normalized = (value - vmin) / (vmax - vmin)
    idx = int(normalized * n_buckets)
    return max(0, min(n_buckets - 1, idx))


def _prepare_geojson(
    values_by_sgg: dict[str, float],
    color_scale: ColorScale,
    selected_sgg: str | None,
    sido: str | None,
) -> dict:
    """GeoJSON features 의 properties 에 fillColor + selected 를 주입한 복사본 반환."""
    raw = load_metro_geojson()
    features = raw["features"]
    if sido and sido in _SIDO_PREFIX:
        prefix = _SIDO_PREFIX[sido]
        features = [f for f in features if f["properties"]["code"].startswith(prefix)]

    ramp = _COLOR_RAMPS[color_scale]
    values = [values_by_sgg.get(f["properties"]["name"], 0.0) for f in features]
    positive = [v for v in values if v and v > 0]
    vmin = min(positive) if positive else 0.0
    vmax = max(positive) if positive else 1.0

    out = []
    for f, v in zip(features, values):
        fc = copy.deepcopy(f)
        props = fc.setdefault("properties", {})
        if v and v > 0:
            props["fillColor"] = ramp[_pick_bucket(v, vmin, vmax, len(ramp))]
        else:
            props["fillColor"] = "#2a2a2e"
        props["selected"] = props["name"] == selected_sgg if selected_sgg else False
        props["value"] = v
        out.append(fc)
    return {"type": "FeatureCollection", "features": out}


def _marker_nodes(overlay_markers: list[dict]) -> list:
    nodes = []
    for m in overlay_markers:
        lat, lon = m.get("lat"), m.get("lon")
        if lat is None or lon is None:
            continue
        nodes.append(
            dl.CircleMarker(
                center=[float(lat), float(lon)],
                radius=max(4, int(m.get("size", 6))),
                color=m.get("color", "#e53935"),
                fillOpacity=0.55,
                weight=1,
                children=[dl.Popup(m["popup"])] if m.get("popup") else None,
            )
        )
    return nodes


def ChoroplethMap(
    id_prefix: str,
    values_by_sgg: dict[str, float],
    *,
    color_scale: ColorScale = "Blues",
    overlay_markers: list[dict] | None = None,
    selected_sgg: str | None = None,
    sido: str | None = None,
    legend_label: str = "",
    height: int = 420,
) -> html.Div:
    """시군구 choropleth map.

    id_prefix 기준으로 내부 ID 부여 (e.g. `f"{id_prefix}-geojson"`).
    클릭 이벤트는 `f"{id_prefix}-geojson"` 의 clickData State 에 feature dict 로 담긴다.
    """
    gj = _prepare_geojson(values_by_sgg, color_scale, selected_sgg, sido)
    center_lat, center_lon, zoom = _SIDO_VIEW.get(sido or "서울특별시", (37.5, 127.0, 9))

    children: list = [
        dl.TileLayer(
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            attribution="© CARTO · © OpenStreetMap",
        ),
        dl.GeoJSON(
            id=f"{id_prefix}-geojson",
            data=gj,
            style=_STYLE_HANDLE,
            hoverStyle={"weight": 2, "color": "#4facfe", "dashArray": "", "fillOpacity": 0.95},
        ),
    ]
    if overlay_markers:
        children.append(dl.LayerGroup(_marker_nodes(overlay_markers)))

    legend_node = (
        html.Div(
            legend_label,
            id=f"{id_prefix}-legend",
            className="choropleth-legend",
        )
        if legend_label
        else None
    )

    return html.Div(
        className="choropleth-wrap",
        style={"position": "relative", "height": f"{height}px"},
        children=[
            dl.Map(
                id=f"{id_prefix}-map",
                center=[center_lat, center_lon],
                zoom=zoom,
                scrollWheelZoom=False,
                zoomControl=True,
                style={"height": "100%", "width": "100%"},
                children=children,
            ),
            legend_node,
        ],
    )
