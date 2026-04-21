// dash-leaflet GeoJSON style 함수 — hideout 로부터 정보를 읽어 feature 별 색상을 결정.
// dash_extensions.assign() 을 쓰지 않고 수동으로 dashExtensions 레지스트리에 등록한다.
window.dashExtensions = Object.assign({}, window.dashExtensions, {
    default: Object.assign({}, (window.dashExtensions && window.dashExtensions.default) || {}, {
        // 각 feature 에 시군구 이름 툴팁 바인딩
        choroplethOnEachFeature: function (feature, layer) {
            var p = feature.properties || {};
            if (p.name) {
                layer.bindTooltip(p.name, {
                    sticky: true,
                    direction: "top",
                    className: "choropleth-tooltip"
                });
            }
        },
        choroplethStyle: function (feature, context) {
            var p = feature.properties || {};
            var h = (context && context.hideout) || {};
            var sidoPrefix = h.sido_prefix;
            var code = String(p.code || "");

            // sido 필터: 선택된 시도에 속하지 않는 feature 는 완전히 숨김
            if (sidoPrefix && code.indexOf(sidoPrefix) !== 0) {
                return {
                    fillColor: "#000000",
                    weight: 0,
                    color: "transparent",
                    fillOpacity: 0,
                    opacity: 0,
                    interactive: false
                };
            }

            var colors = h.color_by_sgg || {};
            var selected = h.selected_sgg && p.name === h.selected_sgg;
            return {
                fillColor: colors[p.name] || "#2a2a2e",
                weight: selected ? 2.2 : 0.6,
                color: selected ? "#00f2fe" : "#1e1e1e",
                fillOpacity: 0.85,
                opacity: 1,
                dashArray: ""
            };
        }
    })
});
