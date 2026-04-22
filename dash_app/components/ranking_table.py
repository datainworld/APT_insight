"""dash-ag-grid 기반 랭킹 테이블 — 5,000+ 행도 스크롤/정렬 쾌적."""

from __future__ import annotations

from typing import Any, Literal

import dash_ag_grid as dag

RowModel = Literal["clientSide", "infinite", "serverSide"]
RowSelection = Literal["single", "multiple"]


DEFAULT_THEME = "ag-theme-alpine-dark"


def RankingTable(
    id_prefix: str,
    columns: list[dict[str, Any]],
    *,
    row_data: list[dict] | None = None,
    row_model: RowModel = "clientSide",
    page_size: int = 25,
    height: int = 480,
    theme: str = DEFAULT_THEME,
    row_selection: RowSelection | None = None,
    get_row_id: str | None = None,
) -> dag.AgGrid:
    """재사용 가능한 ag-grid 테이블.

    Args:
        id_prefix: 컴포넌트 ID 접두어 (e.g. `page-complex-picker`)
        columns: ag-grid columnDefs (field/headerName/valueFormatter 등)
        row_data: clientSide 모드일 때 초기 데이터. 서버사이드일 땐 None.
        row_model: `clientSide`(기본) / `infinite` / `serverSide`
        page_size: 페이지네이션 크기
        height: 고정 픽셀 높이
        theme: ag-grid CSS 테마 클래스
        row_selection: `"single"` / `"multiple"` — 행 선택 활성화
        get_row_id: 행 클릭 안정성을 위한 JS 표현식 (예: `"params.data.apt_id"`)
    """
    grid_options: dict[str, Any] = {
        "pagination": True,
        "paginationPageSize": page_size,
        "paginationPageSizeSelector": [10, 25, 50, 100],
        "suppressMenuHide": True,
        "animateRows": True,
        "rowHeight": 36,
        "headerHeight": 36,
        "rowModelType": row_model,
    }
    if row_selection:
        grid_options["rowSelection"] = row_selection
        grid_options["suppressRowClickSelection"] = False

    default_col_def = {
        "resizable": True,
        "sortable": True,
        "filter": True,
        "floatingFilter": False,
        "minWidth": 80,
    }

    kwargs: dict[str, Any] = {}
    if get_row_id:
        kwargs["getRowId"] = get_row_id
    return dag.AgGrid(
        id=f"{id_prefix}-grid",
        columnDefs=columns,
        rowData=row_data if row_model == "clientSide" else None,
        defaultColDef=default_col_def,
        dashGridOptions=grid_options,
        className=theme,
        style={"height": f"{height}px", "width": "100%"},
        **kwargs,
    )
