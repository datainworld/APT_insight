"""Plotly figure factories for the dashboard."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go

from dash_app.db import load_metro_geojson
from dash_app.theme import (
    ACCENT_1,
    ACCENT_2,
    CAT_COLORS,
    CHOROPLETH_COLORSCALE,
    apply_dark_theme,
)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def empty_fig(msg: str = "데이터 없음") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg, showarrow=False, font=dict(color="#777", size=13),
        xref="paper", yref="paper", x=0.5, y=0.5,
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))


def build_trade_trend(df: pd.DataFrame, deal_type: str) -> go.Figure:
    if df.empty:
        return empty_fig()
    color = CAT_COLORS.get(deal_type, ACCENT_1)
    fig = go.Figure(go.Scatter(
        x=df["deal_date"],
        y=df["count"],
        mode="lines",
        line=dict(color=color, width=1),
        fill="tozeroy",
        fillcolor=_hex_to_rgba(color, 0.18),
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>%{y}건<extra></extra>",
    ))
    apply_dark_theme(fig, margin=dict(l=48, r=16, t=10, b=40))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(type="date", tickformat="%y-%m-%d")
    fig.update_yaxes(title=dict(text="거래건수", font=dict(size=10)))
    return fig


def build_price_change(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_fig()
    # 만원/㎡ → 억원/㎡ 기준이 커서 화면 범위에 맞게 그대로 만원/㎡ 단위로 표시
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["ym"], y=df["avg_per_m2"], name="평균가",
        mode="lines+markers",
        line=dict(color=ACCENT_1, width=2, shape="spline"),
        marker=dict(size=4),
        fill="tozeroy",
        fillcolor=_hex_to_rgba(ACCENT_1, 0.10),
        hovertemplate="<b>%{x}</b><br>평균 %{y:,.0f}만원/㎡<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["ym"], y=df["median_per_m2"], name="중앙값",
        mode="lines",
        line=dict(color=ACCENT_2, width=1.5, dash="dot"),
        hovertemplate="<b>%{x}</b><br>중앙 %{y:,.0f}만원/㎡<extra></extra>",
    ))
    apply_dark_theme(fig, margin=dict(l=56, r=16, t=24, b=36))
    fig.update_yaxes(title=dict(text="만원/㎡", font=dict(size=10)))
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.12, font=dict(size=11)))
    return fig


# Approximate bbox centers (lat, lon) for the three sido used as choropleth focus
_SIDO_CENTERS = {
    "서울특별시": (37.5665, 126.9780, 9.3),
    "경기도":    (37.4138, 127.5183, 7.8),
    "인천광역시": (37.4563, 126.7052, 9.8),
}


def build_choropleth(df_counts: pd.DataFrame, sido: str, selected_sgg: str | None = None) -> go.Figure:
    geojson = load_metro_geojson()
    if df_counts.empty:
        counts_by_sgg = {}
    else:
        counts_by_sgg = dict(zip(df_counts["sgg"], df_counts["count"]))

    # Only show features within the chosen sido (GeoJSON has all 77 metro sgg;
    # we filter by code prefix: 11=서울, 28=인천, 31=경기).
    prefix = {"서울특별시": "11", "인천광역시": "28", "경기도": "31"}.get(sido)
    if prefix:
        features = [f for f in geojson["features"] if f["properties"]["code"].startswith(prefix)]
    else:
        features = geojson["features"]

    locations = [f["properties"]["name"] for f in features]
    z = [counts_by_sgg.get(name, 0) for name in locations]

    scoped_gj = {"type": "FeatureCollection", "features": features}

    fig = go.Figure(go.Choroplethmapbox(
        geojson=scoped_gj,
        featureidkey="properties.name",
        locations=locations,
        z=z,
        colorscale=CHOROPLETH_COLORSCALE,
        marker=dict(line=dict(color="#1e1e1e", width=0.4), opacity=0.88),
        customdata=locations,
        hovertemplate="<b>%{location}</b><br>%{z:,}건<extra></extra>",
        colorbar=dict(
            title=dict(text="거래건수", font=dict(size=10, color="#a0a0a0")),
            thickness=10, len=0.5, x=0.98, xanchor="right",
            tickfont=dict(size=9, color="#a0a0a0"),
        ),
    ))

    # highlight selected sgg with a second trace (transparent z, bright outline)
    if selected_sgg and selected_sgg != "전체":
        highlight = [f for f in features if f["properties"]["name"] == selected_sgg]
        if highlight:
            fig.add_trace(go.Choroplethmapbox(
                geojson={"type": "FeatureCollection", "features": highlight},
                featureidkey="properties.name",
                locations=[selected_sgg],
                z=[1],
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                showscale=False,
                marker=dict(line=dict(color=ACCENT_2, width=2), opacity=1),
                hoverinfo="skip",
            ))

    lat, lon, zoom = _SIDO_CENTERS.get(sido, (37.5665, 126.9780, 8.5))
    fig.update_layout(
        mapbox_style="carto-darkmatter",
        mapbox_zoom=zoom,
        mapbox_center=dict(lat=lat, lon=lon),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Pretendard", color="#a0a0a0"),
    )
    return fig


def build_dot_map(df: pd.DataFrame, sido: str) -> go.Figure:
    lat, lon, zoom = _SIDO_CENTERS.get(sido, (37.5665, 126.9780, 8.5))
    if df.empty or df["latitude"].isna().all():
        fig = go.Figure(go.Scattermapbox(lat=[], lon=[]))
    else:
        plot_df = df.dropna(subset=["latitude", "longitude"]).copy()
        max_count = plot_df["count"].max() or 1
        sizes = plot_df["count"].apply(lambda c: 6 + 22 * math.sqrt(c / max_count))
        hover = plot_df.apply(
            lambda r: f"<b>{r['apt_name']}</b><br>{r['sgg'] or ''} {r['admin_dong'] or ''}<br>거래 {int(r['count']):,}건",
            axis=1,
        )
        fig = go.Figure(go.Scattermapbox(
            lat=plot_df["latitude"],
            lon=plot_df["longitude"],
            mode="markers",
            marker=dict(
                size=sizes,
                color="#e53935",
                opacity=0.55,
                sizemode="diameter",
            ),
            text=hover,
            hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        mapbox_style="carto-darkmatter",
        mapbox_zoom=zoom,
        mapbox_center=dict(lat=lat, lon=lon),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Pretendard", color="#a0a0a0"),
        showlegend=False,
    )
    return fig
