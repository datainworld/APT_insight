"""Phase C.1 페이지 레이아웃 import + 스켈레톤 확인.

주의: `dash.register_page()` 는 `Dash(...)` 인스턴스화 후에만 동작하므로
페이지 모듈을 import 하기 전에 `dash_app.app` 을 먼저 import 해야 한다.
"""

from __future__ import annotations

# Instantiate app first — pages can only register_page after Dash is created.
from dash_app.app import app  # noqa: F401


def test_region_page_registered() -> None:
    from dash_app.pages import region

    assert region.layout is not None


def test_gap_page_registered() -> None:
    from dash_app.pages import gap

    assert gap.layout is not None


def test_invest_page_registered() -> None:
    from dash_app.pages import invest

    assert invest.layout is not None


def test_all_phase_c1_pages_in_registry() -> None:
    import dash

    paths = {v["path"] for v in dash.page_registry.values()}
    for p in ("/region", "/gap", "/invest"):
        assert p in paths


def test_region_layout_has_kpi_strip_and_map() -> None:
    from dash_app.pages.region import layout

    classnames = [getattr(c, "className", "") for c in layout.children]
    assert any("kpi-strip" in (cn or "") for cn in classnames)
    assert any("row2-28" in (cn or "") for cn in classnames)
