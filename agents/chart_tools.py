"""Plotly 차트 생성 도구.

SQL 에이전트의 쿼리 결과를 받아 인터랙티브 차트를 생성한다.
Chainlit의 cl.Plotly(figure)로 렌더링된다.
"""

import json

import plotly.graph_objects as go
from langchain.tools import tool


@tool
def generate_chart(chart_type: str, title: str, data: str) -> str:
    """데이터를 기반으로 Plotly 차트를 생성합니다.

    chart_type: "line" | "bar" | "scatter"
    title: 차트 제목 (한국어)
    data: JSON 문자열. 형식:
      - line/scatter: {"x": [...], "y": [...], "labels": ["시리즈명"]}
      - bar: {"categories": [...], "values": [...], "labels": ["시리즈명"]}
    반환: Plotly Figure JSON 문자열
    """
    d = json.loads(data)
    fig = go.Figure()

    if chart_type == "bar":
        fig.add_trace(go.Bar(
            x=d.get("categories", []),
            y=d.get("values", []),
            name=d.get("labels", [""])[0] if d.get("labels") else "",
        ))
    elif chart_type == "scatter":
        fig.add_trace(go.Scatter(
            x=d.get("x", []),
            y=d.get("y", []),
            mode="markers",
            name=d.get("labels", [""])[0] if d.get("labels") else "",
        ))
    else:  # line (default)
        fig.add_trace(go.Scatter(
            x=d.get("x", []),
            y=d.get("y", []),
            mode="lines+markers",
            name=d.get("labels", [""])[0] if d.get("labels") else "",
        ))

    fig.update_layout(title=title)
    return fig.to_json()
