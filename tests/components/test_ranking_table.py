"""RankingTable + ChoroplethMap 렌더 스모크 테스트."""

from __future__ import annotations

from unittest.mock import patch


def test_ranking_table_renders() -> None:
    from dash_app.components.ranking_table import RankingTable

    columns = [
        {"field": "sgg", "headerName": "자치구"},
        {"field": "count", "headerName": "거래건수"},
    ]
    grid = RankingTable("t", columns, row_data=[{"sgg": "강남구", "count": 123}])
    assert grid.id == "t-grid"
    assert grid.columnDefs == columns
    assert grid.dashGridOptions["pagination"] is True


def test_choropleth_map_renders_with_stubbed_geojson() -> None:
    fake_geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "강남구", "code": "11230"},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
            },
            {
                "type": "Feature",
                "properties": {"name": "서초구", "code": "11220"},
                "geometry": {"type": "Polygon", "coordinates": [[[1, 0], [1, 1], [2, 1], [2, 0], [1, 0]]]},
            },
        ],
    }
    with patch("dash_app.components.choropleth_map.load_metro_geojson", return_value=fake_geo):
        from dash_app.components.choropleth_map import ChoroplethMap

        node = ChoroplethMap(
            "home-map",
            values_by_sgg={"강남구": 100, "서초구": 50},
            color_scale="Blues",
            sido="서울특별시",
            selected_sgg="강남구",
        )
    assert node.className == "choropleth-wrap"
    # dl.Map is first child
    assert node.children[0].id == "home-map-map"
