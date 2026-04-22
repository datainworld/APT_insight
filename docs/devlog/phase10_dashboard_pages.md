# Phase 10: 대시보드 6페이지 구현 — 평당가 정합성과 GeoJSON 교체

> 날짜: 2026-04-20 ~ 2026-04-21
> 커밋: `456effc`, `7436b1b`, `7671ebd`, `8128bde`, `1e28d5a`
> 스펙: Phase C.1 / C.2 / C.3

## 목표

Phase 9 의 스켈레톤 위에 실데이터 기반 **6페이지** 를 구현한다. Phase C 는 스펙상 2주 규모라 내부 분할:

- **C.1** — `/region`, `/gap`, `/invest` (사이드바 필터 활용 페이지 3개)
- **C.2** — `/complex`, `/insight` (검색 기반 / RAG)
- **C.3** — 홈 업그레이드 (스펙 3.1 의 신규 구성)

그 사이에 발견된 버그를 2건의 fix 커밋으로 정리:
- `7436b1b` — 네비 라우팅 오작동, `gap_queries` PG date 뺄셈
- `7671ebd` — GeoJSON 파일 자체 품질 이슈, 시군구명 정규화

---

## 1. Phase C.1 — region / gap / invest (커밋 `456effc`)

### 1.1 설계 원칙

세 페이지 모두 **동일한 구조**:
1. 페이지 헤더 + 범위 표시
2. KPI 스트립 (3~5개)
3. 2컬럼: choropleth + 우측 패널 (차트 또는 히스토그램)
4. 하단: ag-grid 랭킹 또는 추가 차트

이 패턴을 지키면 페이지 하나 작성이 ~300줄, 콜백 하나에 모든 출력을 내보내는 단일 refresh 패턴.

### 1.2 새 쿼리 모듈

- `queries/gap_queries.py` — 호가 괴리율
  - `gap_ratio_by_sgg(sido)` — 시군구별 평균 괴리 + 의심 단지수(+10% 초과) + 평균 노출 기간
  - `gap_ratio_by_complex(sido, sgg, limit)` — 단지별 상세
- `queries/invest_queries.py` — 갭투자 지표
  - `invest_by_sgg(sido)` — 전세가율 · 중위 갭 · 전월세전환율
  - `invest_by_complex(sido, sgg, limit)` — 매력도 점수 랭킹

**매핑 제약**: `gap_queries` 는 `complex_mapping` 에 연결된 단지만 집계. 매핑 커버율(현재 ~80%) 이 분석 범위 한계. `/gap` 페이지 상단에 `cover N%` 뱃지로 사용자에게 노출.

### 1.3 URL 쿼리 동기화 (`/region`)

홈에서 시군구 클릭 시 `/region?sgg=강남구` 로 이동하는 진입점. one-way 동기화만 구현:

```python
@callback(
    Output("f-sgg", "value", allow_duplicate=True),
    Output("f-area", "value", allow_duplicate=True),
    Input("_url", "search"),
    State("_url", "pathname"),
    prevent_initial_call="initial_duplicate",
)
def _sync_from_url(search, pathname):
    if pathname != "/region" or not search:
        raise PreventUpdate
    qs = parse_qs(search.lstrip("?"))
    sgg = qs.get("sgg", [None])[0]
    area = qs.get("size", [None])[0]
    return sgg or dash.no_update, area or dash.no_update
```

역방향(필터 변경 → URL 업데이트) 은 무한 루프 방지 로직이 복잡해 Phase E 로 연기.

### 1.4 발견된 버그 (`7436b1b`)

#### 1.4.1 네비 라우팅 오작동

사용자 제보: **호가 괴리 / 투자 지표** 링크 클릭 시 **단지 상세** 로 이동. 증상이 링크별로 달라 한참 원인 파악.

**디버깅 절차**:
1. 서버 페이지 레지스트리 확인 — 7개 path 모두 정상 등록 ✓
2. `/_dash-layout` endpoint 에서 각 Link href 확인 — 모두 정상 ✓
3. 직접 URL 타이핑 (`/gap`, `/invest`) — 정상 페이지 로드 ✓
4. 클릭만 이상 → dcc.Link 의 click handler 문제로 좁힘

원인은 `dcc.Link` 의 `id={"role": "page-nav", "path": path}` **패턴 매칭 딕셔너리 ID** 와 Dash 4.x의 내부 click routing 충돌. 4 번째/5 번째 링크가 근처 링크로 오라우팅되는 현상.

**해결**: `html.A` + `href=path` 로 교체. SPA 의 instant navigation 은 잃지만 전체 페이지 재로드 비용은 (~200ms) 페이지별 DB 쿼리 (~500ms) 대비 무시할 만함.

```python
def _nav_link(path, name, icon):
    return html.A(
        [_fa(icon), html.Span(name)],
        href=path,
        id=nav_link_id(path),  # 문자열 id 로 변경
        className="",
    )
```

교재 포인트: **라이브러리 버전 업데이트로 내부 동작이 바뀔 수 있다**. `dcc.Link` 는 Dash 2 까지는 무난했으나 4.x 에서 동일 컴포넌트가 이슈. MRU(Most Recently Updated) 라이브러리는 신중하게.

#### 1.4.2 Postgres `date - date` 뺄셈 타입

`gap_queries.py` 의 매물 노출 기간 계산:

```sql
AVG(EXTRACT(EPOCH FROM (CURRENT_DATE - first_seen_date)) / 86400.0) AS avg_days_listed
```

실행 시 `pg_catalog.extract(unknown, integer)` 에러. `date - date` 는 Postgres 에서 `INTERVAL` 이 아니라 `INTEGER` (일수) 반환 → `EXTRACT(EPOCH ...)` 적용 불가.

**수정**: `AVG((CURRENT_DATE - first_seen_date)::int)`. 이미 일수 단위라 EPOCH 변환 불필요.

---

## 2. GeoJSON 전면 교체 (커밋 `7671ebd`)

### 2.1 증상

사용자 제보: 지도에 **대각선 스트라이프 아티팩트**. 원래 시군구 경계가 보여야 할 곳에 길게 늘어진 사선.

### 2.2 원인 1: GeometryCollection feature

원본 `data/maps/metro_sgg.geojson` 구조 검사:

```
Total features: 77
Geometry types: {'Polygon': 32, 'MultiPolygon': 43, 'GeometryCollection': 2}
```

**2개 feature 가 `GeometryCollection` 타입** (code 23060 인천 모 지역). 내부 구조:
```
geometries: [
    {"type": "LineString", "coordinates": [...]},
    {"type": "Polygon", "coordinates": [...]}
]
```

Leaflet 은 GeometryCollection 을 그릴 때 LineString 을 폴리곤 스타일(`fill`)과 함께 그리려다 대각선 아티팩트 생성.

**임시 해결**: 로드 시 `_sanitize_polygons()` 로 GeometryCollection → Polygon/MultiPolygon 만 추출. 하지만 여전히 아티팩트 일부 잔존 → 원본 파일 자체의 polygon quality 가 낮은 것으로 의심.

### 2.3 근본 해결: 파일 교체

사용자 요청: **"서울, 경기, 인천의 행정경계 파일을 찾아야 할"**. 후보:
- `southkorea/southkorea-maps` (GitHub, MIT) ← 선택
- 국가공간정보포털 / VWorld API / 통계청 SGIS

`kostat/2013/json/skorea_municipalities_geo_simple.json` (380KB) 다운로드 → `scripts/rebuild_metro_geojson.py` 로 수도권만(prefix 11/23/31) 필터 → 79개 feature, 74KB, **GeometryCollection 없음**.

```
Geometry types: {'Polygon': 75, 'MultiPolygon': 4}
```

### 2.4 시군구명 불일치 해결

신규 파일과 DB (`rt_complex.sgg_name`) 의 이름 대조 스크립트 (`scripts/check_sgg_names.py`) 실행 결과:

| 시도 | 지도 | DB | 교집합 | 불일치 |
|---|---:|---:|---:|---|
| 서울특별시 | 25 | 25 | 25 | 완전 일치 |
| 인천광역시 | 10 | 9 | 8 | `남구` (2018년 개명→미추홀구), `옹진군` |
| 경기도 | 44 | 45 | 23 | **공백 차이** + 화성시 세분화 |

경기도 21개 불일치 — 전부 `고양시덕양구` (지도) vs `고양시 덕양구` (DB) 공백 유무. 화성시는 DB 에만 `화성시 동탄구` / `화성시 병점구` 세분, 지도엔 단일 `화성시`.

**`dash_app/geo_names.py` 신설**:

```python
_OLD_TO_NEW_INCHEON = {"남구": "미추홀구"}

_COMPOUND_SI_GU = {
    "고양시덕양구": "고양시 덕양구",
    "고양시일산동구": "고양시 일산동구",
    # ... 21개
    "용인시처인구": "용인시 처인구",
}

def normalize_geo_name(name: str, sido_code_prefix: str) -> str:
    if sido_code_prefix == "23" and name in _OLD_TO_NEW_INCHEON:
        return _OLD_TO_NEW_INCHEON[name]
    return _COMPOUND_SI_GU.get(name, name)

def collapse_db_sgg_to_geo(values_by_sgg, *, aggregator="mean") -> dict:
    """'화성시 동탄구' + '화성시 병점구' 를 '화성시' 로 합산."""
    parents: dict[str, tuple[float, int]] = {}
    out: dict[str, float] = {}
    for k, v in values_by_sgg.items():
        if k.startswith("화성시 "):
            total, n = parents.get("화성시", (0.0, 0))
            parents["화성시"] = (total + float(v), n + 1)
        else:
            out[k] = float(v)
    for parent, (total, n) in parents.items():
        out[parent] = (total / n) if aggregator == "mean" else total
    return out
```

- `normalize_geo_name` 은 **지도 로드 시점** 에 적용 — geo feature 의 properties.name 을 DB 형식으로 보정
- `collapse_db_sgg_to_geo` 는 **콜백 내부** 에서 적용 — DB 값을 지도 폴리곤에 매핑하기 전

### 2.5 `hideout` 패턴 재설계

원 설계: 콜백이 `dl.GeoJSON.data` prop 을 업데이트 (features 마다 `properties.fillColor` 수정). 문제: Leaflet GeoJSON 이 `data` 변경 시 **기존 layer 를 제거하지 않고 새 layer 를 덧그리는 버그**. 사용자가 토글을 여러 번 누르면 폴리곤이 겹쳐 그려짐.

해결: **data 를 정적(한 번 로드된 전체 77 feature)으로 고정**. 색상/선택 상태는 `hideout` prop 에 payload 로 실어 보내 **client-side style 함수가 읽도록** 변경:

```python
# dash_app/components/choropleth_map.py
def build_hideout(values_by_sgg, color_scale, selected_sgg, sido, *,
                  metric, metric_label, value_format) -> dict:
    return {
        "color_by_sgg": compute_color_by_sgg(values_by_sgg, color_scale),
        "value_by_sgg": {k: float(v) if v else None for k, v in values_by_sgg.items()},
        "selected_sgg": selected_sgg,
        "sido_prefix": _SIDO_PREFIX.get(sido),
        "metric": metric, "metric_label": metric_label, "value_format": value_format,
    }
```

클라이언트 JS (`assets/choropleth_style.js`):

```javascript
choroplethStyle: function (feature, context) {
    var h = (context && context.hideout) || {};
    window.__mapHideout = h;  // 툴팁 fn 에서 참조

    var p = feature.properties || {};
    var code = String(p.code || "");
    // sido 밖 feature 는 투명화
    if (h.sido_prefix && code.indexOf(h.sido_prefix) !== 0) {
        return { fillOpacity: 0, opacity: 0, interactive: false, ... };
    }
    var colors = h.color_by_sgg || {};
    var selected = h.selected_sgg && p.name === h.selected_sgg;
    return {
        fillColor: colors[p.name] || "#2a2a2e",
        weight: selected ? 2.2 : 0.6,
        color: selected ? "#00f2fe" : "#1e1e1e",
        ...
    };
}
```

**사이드 이펙트 주의**: style 함수 내부에서 `window.__mapHideout = h` 저장. onEachFeature 가 바인딩한 tooltip 함수가 호버 시점에 이 전역을 읽어 현재 지표 + 값 렌더.

### 2.6 `dash_extensions.assign` 의 함정

스펙은 `dash_extensions.javascript.assign(js_code)` 로 style 함수를 등록하라고 권장. 하지만 **`dash_extensions` 의 JS 번들은 해당 라이브러리 컴포넌트 (e.g. `dash_extensions.EventListener`) 가 페이지에 하나라도 있어야 로드됨**. 우리는 그걸 안 쓰니 `assign()` 핸들이 dead.

**우회**: `assets/choropleth_style.js` 를 직접 작성하고 전역 레지스트리에 수동 등록 →

```javascript
window.dashExtensions = Object.assign({}, window.dashExtensions, {
    default: Object.assign({}, (window.dashExtensions && window.dashExtensions.default) || {}, {
        choroplethStyle: function (feature, context) { ... },
        choroplethOnEachFeature: function (feature, layer) { ... },
    })
});
```

그리고 Python 쪽에서 handle 구성:

```python
_STYLE_HANDLE = {"variable": "dashExtensions.default.choroplethStyle"}
_ON_EACH_FEATURE = {"variable": "dashExtensions.default.choroplethOnEachFeature"}
```

dash-leaflet 이 이 변수 이름을 런타임에 `window` 에서 lookup 해 호출.

### 2.7 한국어 라벨 타일

사용자 요청: **"배경지도의 지역명이 한국어로"**. CARTO darkmatter 타일은 영문 라벨만 지원.

선택: OSM 표준 타일 + **CSS `filter: invert(1) hue-rotate(180deg) brightness(0.85) saturate(0.3)`** 로 다크 톤으로 반전. 한국어 라벨 유지.

```css
.choropleth-wrap .leaflet-tile-pane {
    filter: invert(1) hue-rotate(180deg) brightness(0.85) saturate(0.3);
}
```

Leaflet 의 tile-pane 에만 필터를 적용해 오버레이(GeoJSON polygon) 는 영향 없음.

### 2.8 Scroll wheel zoom

사용자 요청: 마우스 휠로 지도 크기 조절. dl.Map 의 `scrollWheelZoom=True` 로 활성화. 기본값 비활성이 의외.

### 2.9 Hover tooltip

사용자 요청: **지도 호버 시 지역명 + 값 표시**. `onEachFeature` JS 가 `layer.bindTooltip(fn)` 으로 동적 툴팁 바인딩:

```javascript
choroplethOnEachFeature: function (feature, layer) {
    var p = feature.properties || {};
    if (!p.name) return;
    layer.bindTooltip(function () {
        // show 시점마다 호출되므로 최신 hideout 참조 가능
        var h = window.__mapHideout || {};
        var v = (h.value_by_sgg || {})[p.name];
        var label = h.metric_label || "";
        var fmt = h.value_format || "count";
        var body;
        if (v == null || isNaN(v)) body = "—";
        else if (fmt === "ppm2") body = Math.round(v).toLocaleString() + " 만원/㎡";
        else if (fmt === "percent") body = v.toFixed(1) + "%";
        else body = Math.round(v).toLocaleString() + " 건";
        return "<b>" + p.name + "</b><br>" + (label ? label + " · " : "") + body;
    }, { sticky: true, direction: "top", className: "choropleth-tooltip" });
}
```

---

## 3. Phase C.2 — complex + insight (커밋 `8128bde`)

### 3.1 `/complex` — 단지 상세 페이지

**검색 UX 판단** (사용자 제시 2옵션):
- (1) `dcc.Dropdown` 서버사이드 부분일치 (타이핑 → 자동완성)
- (2) ag-grid 목록 선행 선택

사용자 최종: **하이브리드**. Dropdown 으로 단지명 직접 검색 + 그 아래 ag-grid 로 시군구별 상위 200 단지 탐색. 행 클릭 → Dropdown 값 자동 갱신.

```python
# 1) 검색 자동완성
@callback(
    Output("page-complex-search", "options"),
    Input("page-complex-search", "search_value"),
    State("page-complex-search", "value"),
)
def _search_options(search_value, current_value):
    if len(search_value or "") < 1:
        raise PreventUpdate
    rows = rtq.search_complexes(search_value, limit=30)
    return [{"label": f"{r['apt_name']} · {r['sgg_name']}", "value": r["apt_id"]} for r in rows]

# 2) ag-grid picker row click → Dropdown
@callback(
    Output("page-complex-search", "value", allow_duplicate=True),
    Input("page-complex-picker-grid", "selectedRows"),
    prevent_initial_call=True,
)
def _picker_to_dropdown(selected):
    ...
```

**4 탭** (실거래 추이 / 호가 추이 / 전월세 / 층×면적 매트릭스) 각각 `dcc.Graph` 1개. 탭 전환 시 동일 콜백이 tab 값을 읽어 다른 figure 생성.

### 3.2 평당가 정합성 — 가장 중요한 리팩토링

**사용자 문제 제기**:
> 아파트 단지별로 다수의 면적이 존재하며, 거래(매매, 전세, 월세) 가격은 면적에 종속됨. 따라서, 단지별 평균가는 의미 없음. 단지별 면적 단위(예,  84, 59제곱미터)로 비교해야 의미가 있음.

이 원칙을 코드 전반에 적용해야 하는 대규모 리팩토링:

**SQL 레벨**:
- `gap_queries.py`: `median_deal`(만원) → `median_trade_ppm2` (만원/㎡), `avg_ask` → `avg_ask_ppm2`
- `invest_queries.py`: `median_sale` → `median_sale_ppm2`, `gap` → `gap_ppm2`, `jeonse_ratio` 는 dimensionless 라 유지

**UI 레벨**:
- `/region` 랭킹 테이블: `avg_price_6m` 컬럼 제거
- `/complex` KPI: "평균 매매가" → **"주력 면적"** (12M 거래 최다 전용면적, rt_queries 서브쿼리로 추가)
- `/gap` scatter 축: "실거래 중위 (만원)" → "실거래 평당 중위 (만원/㎡)"
- `/invest` 테이블/KPI: 모두 평당 표기

**검증 결과**:
- 송파구 평균 호가 괴리율: 22.8% → **16.5%** (면적 정규화 효과로 오버에스티메이션 제거)
- 강남구 미성아파트: 실거래 평당 1,280만원/㎡ vs 호가 평당 2,318만원/㎡ → 괴리 +81% (명확히 호가 과열)

교재 포인트: **도메인 상식 (다면적 혼재)** 이 소프트웨어 요구사항에 녹아들지 않으면 통계가 왜곡된다. 이 원칙은 실거래 분석의 ABC 이지만, 코드만 보면 눈에 띄지 않는다. 데이터 분석 프로젝트에서는 도메인 전문가 리뷰가 필수.

### 3.3 `/insight` — 뉴스 & RAG

3컬럼: 좌 (뉴스 타임라인) · 중 (heatmap) · 우 (RAG 검색).

**3단계 fallback heatmap** (스펙 3.6):
- `regional >= 3` → 시군구 × 날짜 히트맵 (Oranges)
- `0 < regional < 3` → 카테고리 × 날짜 (Blues, 설명 라인에 "지역 뉴스 소량 → 카테고리로 대체")
- `regional == 0` → 카테고리 × 날짜

**RAG 검색** — `agents.config.get_vector_store()` 에서 `similarity_search(query, k=3)` 호출 → top 3 스니펫 렌더. 업로드 기능은 Phase 11 에서.

---

## 4. Phase C.3 — 홈 업그레이드 (커밋 `1e28d5a`)

### 4.1 스펙 3.1 신규 구성

KPI 4 + 메인 choropleth + 뉴스 4건 + 36M dual-axis + TOP 5 bar → 사용자 피드백으로 축소.

### 4.2 사용자 피드백 5건 (이 phase 의 핵심)

1. **"월 거래량"은 최근 1개월은 부적절** — 거래 신고 30일 유예 때문.
   - 해결: **2개월 전 (직전 완료월)** vs **3개월 전** 비교. 값에 `2026-02` 식 ym 명시.

2. **활성 매물 매매/전세/월세 구분 필요**
   - `nv_queries.active_listing_breakdown_by_sgg(sido)` 신설. FILTER 절로 trade_type 분해.
   - KPI delta 슬롯에 `매매 N · 전세 M · 월세 K` 인라인 표기.

3. **활성 매물은 선행 지표 — 시각 차별화**
   - `KpiCard(kind="leading")` 추가 — 좌측 주황 바 + 우상단 `선행` 뱃지 (CSS `.kpi-tile--leading`).

4. **KPI ↔ 맵 choropleth 연동**
   - 별도 토글 버튼 제거. KPI 타일 자체를 클릭 가능하게 (`KpiCard(clickable=True)`).
   - 각 KPI 고유 색상 매핑: 거래량(Blue) / 평당가(Purple) / 전세가율(Green) / 활성매물(Orange)
   - 맵 색상 램프도 동일 (Purples 램프는 `choropleth_map.py` 에 신규 추가).
   - `.kpi-tile--selected.kpi-tile--color-purple` 같은 per-color CSS.

5. **뉴스 4건 + TOP 5 제거, 맵 우측에 36M trend chart**
   - 레이아웃 단순화: `row2-28: [map | trend]` 1행만.

추가 피드백 3건 (2차 반복):
- "평당가/전세가율/활성 매물 카드에 타이틀 레이블 미표시" → `dmc.Tooltip` 가 Provider 없어 렌더 실패 → **native `title` 속성으로 교체** (Phase 11 에서 완전 이전).
- "전세가율·활성 매물 비교 기간은 1개월로" → `_jeonse_ratio_1m` / `_active_listing_pop` SQL 재작성.
- "맵 색상 값 호버 표시" → `hideout.value_by_sgg` + 동적 tooltip (§2.9).

추가 피드백 4건 (3차 반복):
- "거래량은 매매/전세/월세 분해" → `_trade_volume_breakdown` 신설 (직전 완료월 기준).
- "델타는 혼란 유발 → 제거" → KpiCard 의 `delta_id/delta_kind` slot 을 **`detail_id/period_id` 로 일반화**. 방향성 색상(up/down) 삭제.
- "각 KPI 기준 시기 명시" → `period_id` 슬롯이 label 바로 아래 subtitle 로 시기 표시 (예: `2026-02 (직전 완료월)`, `2025-10 ~ 2026-04 · 6M 중위`).

### 4.3 필터 단순화 (같은 커밋)

사용자 피드백 5건:
- 읍면동(`f-dong`) 제거 — 시군구 단위까지만 필터링
- 기간 슬라이더 max 120→36 (3년)
- "조건 적용"/"초기화" 버튼 제거 (live 반영, reset 불필요)
- 드롭다운 크기/폰트 축소 (28px · 12px bold white)
- 거래유형 seg 버튼 축소 (11px · 4px padding)

**Dash 4.x 클래스명 변경 함정**: 드롭다운 CSS 적용 안 됨. 원인은 Dash 4 에서 `dcc.Dropdown` 이 `.Select-*` → **`.dash-dropdown-*`** 로 클래스명 전면 변경. 기존 CSS 가 dead selector.

```javascript
// async-dropdown.js 를 grep 해서 실제 클래스 확인
className:"dash-dropdown-trigger"
className:"dash-dropdown-value"
className:"dash-dropdown-content"
className:"dash-dropdown-option"
...
```

### 4.4 전역 필터 콜백 분리

홈 재작성 시 기존 `pages/home.py` 에 있던 cascade 콜백 (`sido→sgg options`, `sgg→dong options`, `period label`, `deal segment`, `reset`) 이 다른 페이지의 사이드바를 망가뜨릴 위험. **`callbacks/filters.py`** 로 분리해 `app.py` 에서 side-effect import.

```python
# dash_app/app.py
from dash_app.callbacks import filters as _filters  # noqa: F401
```

---

## 5. 테스트 요약

| 지표 | Phase C 시작 | Phase C 종료 |
|---|---:|---:|
| 테스트 수 | 36 | 47 |
| ruff 상태 | green | green |
| mypy 에러 | 0 | 0 |

신규 테스트:
- `test_page_layouts.py` — 6 페이지 register_page + layout 존재
- `test_gap_invest_queries.py` — 쿼리 함수 signature smoke
- `test_formatters.py` — 평당가/만원 변환 경계
- `test_ranking_table.py`, `test_status_banner_empty.py` — 컴포넌트 렌더

**pytest 실행 시 주의**: 페이지 모듈 `import` 전에 `dash_app.app` 을 먼저 import 해야 함. `register_page()` 는 `Dash(__name__, use_pages=True)` 인스턴스 생성 이후에만 유효. 미숙지 시 "register_page() must be called after app instantiation" 에러.

---

## 6. 코드 변경 규모 (Phase C 누적)

| 지표 | 값 |
|---|---:|
| 신규 페이지 | 6 (C.1 3개 + C.2 2개 + C.3 홈 교체) |
| 신규 쿼리 모듈 | 4 (gap, invest, 이미 있던 nv/metrics 확장) |
| 신규 JS asset | 1 (`choropleth_style.js` — dash_extensions 우회) |
| 디자인 토큰 신규 | Purples 램프, `.kpi-tile--leading`, `.kpi-tile--color-*` |

---

## 7. 남은 과제 / Phase 11 로 넘어간 것

- **채팅 패널 재작성** — 4단계 크기 + PDF 업로드 + 응답 렌더러
- **TermTip native title 전환** — Phase 10 말미에 `display=label` 로 glossary 라벨 누락 버그는 고쳤지만, `dmc.Tooltip` 제거는 Phase 11 에서 완료

---

## 8. 교재 포인트 요약

1. **사용자 피드백 3차 반복**. 한 번에 모든 요구를 반영하기 어렵다는 점, **빠른 iteration + 명확한 커밋 포인트** 의 가치.
2. **도메인 원칙 (평당가)** 이 코드 전반에 적용되는 리팩토링의 파급. SQL · UI · 용어 사전 전체에서 일관성 유지.
3. **Dash 4.x 클래스명 변경** 같은 라이브러리 내부 변경은 문서화가 부족하다. 실제 JS 번들을 grep 해서 확인하는 디버깅 기법.
4. **패턴 매칭 dict ID** 의 예상치 못한 버그 (`dcc.Link` click routing) — 장점 대비 리스크 평가.
5. **GeometryCollection 이슈** — 공식 GeoJSON 포맷이라도 실제 렌더링 라이브러리가 완벽히 처리하지 않을 수 있다. 정적 자원 품질 검증의 중요성.
6. **Postgres 예약어 (`window`)** — CTE 이름으로 쓰면 구문 에러. 예약어 리스트 참조 습관.
7. **MV 를 cascade 콜백에서 직접 사용** — 쿼리 반복 호출 없이 사전 계산된 집계 활용으로 응답 시간 단축.
