"""지도 시각화 도구 — Choropleth(시군구 히트맵) + 단지 마커 지도.

둘 다 Plotly Figure JSON으로 반환 → Chainlit의 `cl.Plotly` 경로로 렌더링.
GeoJSON: `data/maps/metro_sgg.geojson` (수도권 시군구 경계, properties.name 기준).
"""

import json
from pathlib import Path

import plotly.graph_objects as go
from langchain.tools import tool

from shared.config import BASE_DIR

# 개발(프로젝트 루트)과 프로덕션(/app/assets/maps) 둘 다 지원
_GEOJSON_SEARCH_PATHS = [
    BASE_DIR / "data" / "maps" / "metro_sgg.geojson",
    Path("/app/assets/maps/metro_sgg.geojson"),
]
_CAPITAL_CENTER = [37.5, 127.0]


def _load_geojson() -> dict:
    for p in _GEOJSON_SEARCH_PATHS:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        f"metro_sgg.geojson not found in {[str(p) for p in _GEOJSON_SEARCH_PATHS]}"
    )


@tool
def generate_choropleth(title: str, data: str) -> str:
    """수도권 시군구별 수치 데이터를 색상 히트맵으로 시각화합니다.

    data: JSON 문자열. 형식:
        {"locations": ["강남구", "서초구", ...], "values": [150000, 180000, ...],
         "colorbar_title": "평균 매매가(만원)"}
      - locations: 시군구 한글명. GeoJSON properties.name과 일치해야 한다.
        복합 지역은 공백 없이: "수원시장안구", "성남시분당구", "고양시일산동구" 등.
      - values: 숫자 리스트 (locations와 같은 길이).
      - colorbar_title: 색상 범례 제목 (선택).

    반환: Plotly Figure JSON 문자열.
    사용 상황: 지역별 가격 비교·거래량 분포 등 공간 패턴이 있는 수치 비교.
    """
    d = json.loads(data)
    geo = _load_geojson()

    fig = go.Figure(go.Choroplethmapbox(
        geojson=geo,
        locations=d.get("locations", []),
        z=d.get("values", []),
        featureidkey="properties.name",
        colorscale="YlOrRd",
        marker_opacity=0.65,
        marker_line_width=0.5,
        colorbar_title=d.get("colorbar_title", ""),
    ))
    fig.update_layout(
        title=title,
        mapbox_style="carto-positron",
        mapbox_zoom=8.5,
        mapbox_center={"lat": _CAPITAL_CENTER[0], "lon": _CAPITAL_CENTER[1]},
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
    )
    return fig.to_json()


@tool
def generate_map(title: str, data: str) -> str:
    """개별 아파트 단지를 지도 위 마커로 표시합니다 (hover에 단지명·가격).

    data: JSON 문자열. 형식:
        {"markers": [
           {"lat": 37.5, "lon": 127.0, "name": "단지명", "price": "15억", "extra": "..."}
        ],
         "center": [37.5, 127.0],  # 선택 (없으면 마커 평균 좌표)
         "heatmap": false}          # true면 밀도 히트맵, false면 마커(기본)

    반환: Plotly Figure JSON 문자열.
    사용 상황: 단지 좌표가 있는 개별 데이터 표시 (시세 상위 단지, 조건별 검색 결과 등).
    마커 30개 이상이면 자동 clustering이 적용된다.
    """
    d = json.loads(data)
    markers = d.get("markers", [])
    if not markers:
        return ""

    lats = [m["lat"] for m in markers if "lat" in m and "lon" in m]
    lons = [m["lon"] for m in markers if "lat" in m and "lon" in m]
    if not lats:
        return ""

    center = d.get("center") or [sum(lats) / len(lats), sum(lons) / len(lons)]

    if d.get("heatmap"):
        fig = go.Figure(go.Densitymapbox(
            lat=lats, lon=lons,
            z=[1] * len(lats),
            radius=18,
            colorscale="YlOrRd",
            opacity=0.65,
        ))
    else:
        texts = []
        for m in markers:
            parts = [m.get("name", "")]
            if m.get("price"):
                parts.append(str(m["price"]))
            if m.get("extra"):
                parts.append(str(m["extra"]))
            texts.append("<br>".join(parts))

        fig = go.Figure(go.Scattermapbox(
            lat=lats, lon=lons,
            mode="markers",
            marker={"size": 10, "color": "#d62728"},
            text=texts,
            hoverinfo="text",
            cluster={"enabled": len(markers) >= 30, "maxzoom": 12},
        ))

    fig.update_layout(
        title=title,
        mapbox_style="carto-positron",
        mapbox_zoom=11 if len(markers) < 30 else 9,
        mapbox_center={"lat": center[0], "lon": center[1]},
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
    )
    return fig.to_json()
