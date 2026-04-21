"""dash-leaflet 기반 시군구 choropleth.

렌더 패턴:
    1) `data` prop 에는 수도권 77개 시군구 전체 GeoJSON 을 **정적**으로 바인딩.
       data 가 바뀌면 Leaflet 이 기존 layer 를 잘 못 비우고 겹쳐 그리는 이슈가 있어,
       data 는 항상 동일하게 유지한다.
    2) 시각 상태(색상 / 선택된 sgg / sido 필터)는 전부 `hideout` 에 실어 보낸다.
    3) 클라이언트사이드 style 함수(assets/choropleth_style.js) 가 hideout 을 읽고
       feature 별 fillColor / 선택 강조 / sido 밖 feature 숨김을 결정한다.
"""

from __future__ import annotations

from typing import Literal

import dash_leaflet as dl
from dash import html

from dash_app.db import load_metro_geojson

ColorScale = Literal["Blues", "Oranges", "Greens", "Reds", "Purples"]

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
    "Purples": [
        "#efdcff", "#dcb9ff", "#c597f3", "#ae74e1",
        "#9755cd", "#7b3cb2", "#5e278d", "#401867",
    ],
}

_SIDO_PREFIX = {"서울특별시": "11", "인천광역시": "23", "경기도": "31"}
_SIDO_VIEW = {
    "서울특별시": (37.5665, 126.9780, 10),
    "경기도":    (37.4138, 127.5183, 8),
    "인천광역시": (37.4563, 126.7052, 10),
}

_STYLE_HANDLE = {"variable": "dashExtensions.default.choroplethStyle"}
_ON_EACH_FEATURE = {"variable": "dashExtensions.default.choroplethOnEachFeature"}


def _pick_bucket(value: float, vmin: float, vmax: float, n_buckets: int) -> int:
    if vmax <= vmin:
        return 0
    normalized = (value - vmin) / (vmax - vmin)
    idx = int(normalized * n_buckets)
    return max(0, min(n_buckets - 1, idx))


def compute_color_by_sgg(
    values_by_sgg: dict[str, float],
    color_scale: ColorScale,
) -> dict[str, str]:
    """시군구→색상 hex 매핑. 0/음수는 키를 생략 (JS 쪽에서 default 색을 사용)."""
    ramp = _COLOR_RAMPS[color_scale]
    positive = [v for v in values_by_sgg.values() if v and v > 0]
    if not positive:
        return {}
    vmin = min(positive)
    vmax = max(positive)
    out: dict[str, str] = {}
    for sgg, v in values_by_sgg.items():
        if v and v > 0:
            out[sgg] = ramp[_pick_bucket(v, vmin, vmax, len(ramp))]
    return out


def build_hideout(
    values_by_sgg: dict[str, float],
    color_scale: ColorScale = "Blues",
    selected_sgg: str | None = None,
    sido: str | None = None,
    *,
    metric: str | None = None,
    metric_label: str | None = None,
    value_format: str = "count",
) -> dict:
    """choropleth hideout 페이로드. 콜백 Output 타깃.

    Args:
        values_by_sgg: 지표 원본값 (색상 계산 + 툴팁 표시용)
        metric: 내부 지표 키 (`trade_count` | `ppm2` | `jeonse` | `active` 등)
        metric_label: 툴팁에 표시할 사람 읽기용 이름 (예: "평당 중위 (6M)")
        value_format: 툴팁 포매터 지시자 — `count` | `ppm2` | `percent`
    """
    return {
        "color_by_sgg": compute_color_by_sgg(values_by_sgg, color_scale),
        "value_by_sgg": {k: float(v) if v is not None else None for k, v in values_by_sgg.items()},
        "selected_sgg": selected_sgg,
        "sido_prefix": _SIDO_PREFIX.get(sido) if sido else None,
        "metric": metric,
        "metric_label": metric_label,
        "value_format": value_format,
    }


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
    values_by_sgg: dict[str, float] | None = None,
    *,
    color_scale: ColorScale = "Blues",
    overlay_markers: list[dict] | None = None,
    selected_sgg: str | None = None,
    sido: str | None = None,
    legend_label: str = "",
    height: int = 420,
) -> html.Div:
    """수도권 시군구 choropleth map.

    후속 콜백에서 `f"{id_prefix}-geojson"` 의 `hideout` 를 `build_hideout(...)`
    결과로 갱신하면 색/선택/시도 필터가 동적으로 반영된다.
    클릭은 `clickData` 로 feature 가 담긴다 (properties.name 에서 sgg 획득).
    """
    gj = load_metro_geojson()
    center_lat, center_lon, zoom = _SIDO_VIEW.get(sido or "서울특별시", (37.5, 127.0, 9))
    initial_hideout = build_hideout(values_by_sgg or {}, color_scale, selected_sgg, sido)

    children: list = [
        # OSM 표준 타일 — 한국어 지명 포함. 다크 톤은 CSS invert 필터로 적용 (kit_dashboard.css).
        dl.TileLayer(
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            attribution="© OpenStreetMap contributors",
        ),
        dl.GeoJSON(
            id=f"{id_prefix}-geojson",
            data=gj,
            hideout=initial_hideout,
            style=_STYLE_HANDLE,
            onEachFeature=_ON_EACH_FEATURE,
            hoverStyle={"weight": 2, "color": "#4facfe", "fillOpacity": 0.95},
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
                scrollWheelZoom=True,
                zoomControl=True,
                style={"height": "100%", "width": "100%"},
                children=children,
            ),
            legend_node,
        ],
    )
