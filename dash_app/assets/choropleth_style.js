// dash-leaflet GeoJSON style + onEachFeature — hideout 로부터 색상/툴팁 동적 렌더.
// dash_extensions.assign() 을 쓰지 않고 수동으로 dashExtensions 레지스트리에 등록한다.
window.dashExtensions = Object.assign({}, window.dashExtensions, {
    default: Object.assign({}, (window.dashExtensions && window.dashExtensions.default) || {}, {

        // 각 feature 에 동적 툴팁 바인딩 (이름 + 현재 선택 지표 값).
        // Leaflet 의 bindTooltip 은 fn 을 content 로 받으면 show 시점에 호출하므로,
        // hideout 이 바뀌어도 최신 값을 읽어온다.
        choroplethOnEachFeature: function (feature, layer) {
            var p = feature.properties || {};
            if (!p.name) return;
            layer.bindTooltip(function () {
                var h = window.__mapHideout || {};
                var vals = h.value_by_sgg || {};
                var v = vals[p.name];
                var label = h.metric_label || "";
                var fmt = h.value_format || "count";
                var body;
                if (v == null || isNaN(v)) {
                    body = "—";
                } else if (fmt === "ppm2") {
                    body = Math.round(v).toLocaleString() + " 만원/㎡";
                } else if (fmt === "percent") {
                    body = v.toFixed(1) + "%";
                } else {
                    body = Math.round(v).toLocaleString() + " 건";
                }
                var prefix = label ? (label + " · ") : "";
                return "<b>" + p.name + "</b><br>" + prefix + body;
            }, {
                sticky: true,
                direction: "top",
                className: "choropleth-tooltip"
            });
        },

        // style: hideout 으로부터 feature 별 fillColor/선택 상태/sido 필터 결정.
        // 여기서 window.__mapHideout 에도 저장 → onEachFeature 의 tooltip fn 이 참조.
        choroplethStyle: function (feature, context) {
            var h = (context && context.hideout) || {};
            window.__mapHideout = h;

            var p = feature.properties || {};
            var sidoPrefix = h.sido_prefix;
            var code = String(p.code || "");
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
