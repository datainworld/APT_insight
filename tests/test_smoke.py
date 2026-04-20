"""앱 임포트·멀티페이지 등록 smoke test. DB 연결 불필요."""

from __future__ import annotations


def test_app_imports_and_registers_7_pages() -> None:
    import dash

    from dash_app.app import app
    from dash_app.config import PAGES

    assert app is not None
    # use_pages 가 활성화되면 dash.page_registry 에 7개 등록되어야 함
    expected_paths = {p["path"] for p in PAGES}
    registered_paths = {v["path"] for v in dash.page_registry.values()}
    assert expected_paths.issubset(registered_paths), (
        f"missing: {expected_paths - registered_paths}"
    )


def test_sidebar_shell_renders() -> None:
    from dash_app.components.sidebar import sidebar

    node = sidebar()
    # aside.filter-side 안에 nav + filter body 가 들어있어야 함
    assert node.className == "filter-side"
    assert len(node.children) >= 1
