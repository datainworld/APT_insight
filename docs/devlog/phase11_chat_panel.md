# Phase 11: 플로팅 채팅 패널 재작성 + RAG 파이프라인

> 날짜: 2026-04-21
> 커밋: `27bd90d`, `e7018c7`
> 스펙: Phase D.1 / D.3 / D.4

## 목표

Phase 9 에서 이관만 해둔 기존 채팅 UI(3단계 크기 토글) 를 스펙 6장의 **4단계 패널** 로 재작성한다. 부가로:
- 마크다운·테이블·차트 렌더러 (스펙 6.7)
- **PDF 업로드** 기능 (스펙 7장) — RAG 적재 경로 자체 구축 (agents 수정 금지)
- 장시간 질의 중단 기능

스펙상 D.2 (컨텍스트 주입), D.5 (토큰 스트리밍) 는 사용자 판단으로 스킵.

---

## 1. D.1 — 4단계 패널 (커밋 `27bd90d` 일부)

### 1.1 4단계 크기 상태

스펙 6.1:
| 상태 | 크기 | 위치 |
|---|---|---|
| `minimized` | 56×56 아이콘 | 우하단 고정 |
| `compact` | 400×min(640, 100vh-48) | 우하단 |
| `expanded` | clamp(480, 50vw, 800) × (100vh-24) | 우측 도크 |
| `maximized` | calc(100vw-24) × calc(100vh-24) | 전체 overlay |

기존 FAB(56x56 아이콘 버튼) 과 chat-panel 섹션을 분리 유지 → 스펙대로 **minimized 상태의 패널 자체가 FAB 역할** 을 하도록 통합. 하나의 `html.Section` 에 `data-size` 속성으로 상태 구분.

```python
html.Section(
    id="chat-panel",
    **{"data-size": "minimized"},
    children=[
        html.Button(id="chat-open", className="chat-open-btn", ...),  # minimized 전용
        html.Header(className="chat-hdr", ...),                        # compact 이상에서만
        ...
    ]
)
```

CSS 가 `data-size` 로 분기:
```css
.chat-panel[data-size="minimized"] {
    width: 56px; height: 56px; border-radius: 50%; background: ...gradient;
}
.chat-panel[data-size="minimized"] > :not(.chat-open-btn) { display: none !important; }
.chat-panel[data-size="compact"] { width: 400px; height: min(640px, calc(100vh - 48px)); }
...
```

`transition: all 200ms ease-out` 으로 부드러운 전환.

### 1.2 상태 전환 머신

스펙 6.3 의 4단계 전환표. `dash_app/components/chat_panel/sizes.py` 에 헬퍼:

```python
SIZE_MODES = ("minimized", "compact", "expanded", "maximized")
_ORDER = {mode: i for i, mode in enumerate(SIZE_MODES)}

def next_mode_up(current):   # maximized 에서는 그대로
    idx = _ORDER.get(current, 1)
    return SIZE_MODES[min(idx + 1, len(SIZE_MODES) - 1)]

def next_mode_down(current): # minimized 에서는 그대로 (ESC no-op)
    idx = _ORDER.get(current, 1)
    return SIZE_MODES[max(idx - 1, 0)]
```

### 1.3 헤더 컨트롤 — 4단계 직접 선택 (사용자 피드백 반영)

**초기 구현** (스펙대로): `[−]` `[⇲/⇱]` (smart toggle) `[X]` — 3개 버튼, 한 단계씩 변경.

**사용자 피드백**: "헤더 3버튼 자리에 minimized/compact/expanded/maximized 를 나타내는 아이콘 배치". 직관적이지만 스펙과 다른 방향.

**변경**:
```python
html.Button(_fa("window-minimize"),  id={"role": "chat-size", "mode": "minimized"}, ...)
html.Button(_fa("window-restore"),   id={"role": "chat-size", "mode": "compact"}, ...)
html.Button(_fa("window-maximize"),  id={"role": "chat-size", "mode": "expanded"}, ...)
html.Button(_fa("expand"),           id={"role": "chat-size", "mode": "maximized"}, ...)
```

현재 선택된 mode 버튼은 `.on` 클래스 강조. 패턴 매칭 dict ID 는 헤더 내부 4개 버튼만이라 routing 충돌 없음.

### 1.4 ESC 키 — clientside + Dash Store

스펙 6.3: `ESC` 는 한 단계씩 축소. Dash 콜백은 서버 측에서 실행되므로 키 이벤트를 직접 받을 수 없음. 기존 `assets/chat_enter.js` 확장:

```javascript
document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var panel = document.getElementById("chat-panel");
    if (!panel) return;
    var size = panel.getAttribute("data-size");
    if (!size || size === "minimized") return;
    e.preventDefault();
    // Dash Store 값을 증가시켜 size-transition 콜백 트리거
    if (window.dash_clientside && window.dash_clientside.set_props) {
        var cur = (window.dash_clientside.callback_context?.states
                   ?.["chat-esc-trigger.data"]) || 0;
        window.dash_clientside.set_props("chat-esc-trigger", {
            data: (typeof cur === "number" ? cur : 0) + 1
        });
    }
});
```

Dash 4.x 의 `dash_clientside.set_props` API 활용. 카운터 증가 → `chat-esc-trigger` store 값 변경 → size transition 콜백 Input 으로 감지.

### 1.5 Input 분리로 Chip 오트리거 버그 수정

**증상**: 사용자가 채팅 입력창에 질문을 타이핑하고 Enter 를 누르면 **첫 번째 예시 chip 의 값이 전송**됨.

**원인**: 초기 구현은 send 와 chip 을 한 콜백에서 처리:

```python
@callback(
    Output("chat-msgs", "data"),
    ...
    Input("chat-send", "n_clicks"),
    Input({"role": "chat-chip", "value": ALL}, "n_clicks"),
    ...
)
def _chat_submit(_send, _chip_clicks, input_val, msgs, busy, thread):
    trig = ctx.triggered_id
    ...
```

Dash 가 welcome_msg 를 re-render 할 때 chip 들이 새로 DOM 에 생성됨. 생성 직후 `n_clicks=None` 으로 등록되는데 Dash 가 이 등록 자체를 "trigger" 로 판정하는 경우 발생. `ctx.triggered_id` 가 첫 chip dict 로 찍혀 chip 값이 send 인 것처럼 처리.

**해결**: 콜백을 **2개로 분리**.

```python
@callback(
    Output("chat-msgs", "data"), ...
    Input("chat-send", "n_clicks"),
    State("chat-input", "value"), ...
    prevent_initial_call=True,
)
def _chat_submit_send(n_clicks, input_val, msgs, busy, thread):
    if not n_clicks or busy: raise PreventUpdate
    text = (input_val or "").strip()
    if not text: raise PreventUpdate
    ...

@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Input({"role": "chat-chip", "value": ALL}, "n_clicks"), ...
    prevent_initial_call=True,
)
def _chat_submit_chip(chip_clicks, msgs, busy, thread):
    if not any(chip_clicks or []):  # 초기 렌더 가드
        raise PreventUpdate
    trig = ctx.triggered_id
    ...
```

`any(chip_clicks or [])` 로 최소 한 번이라도 실제 클릭이 있어야 처리.

교재 포인트: Dash 의 **pattern-matching Input 초기 렌더 오트리거** 는 문서화 부족한 함정. 복수 독립 trigger 를 한 콜백에 묶으면 `prevent_initial_call` 만으로 충분치 않을 수 있다.

### 1.6 예시 질의 변경

기존: `"수도권 열지도", "자치구 비교", "급등 실거래"` — 추상적.

사용자 요청 변경:
```python
CHIP_PROMPTS = [
    "강남구 최근 거래 추이",
    "호가 괴리가 큰 단지",
    "갭투자 유망 단지 추천",
]
```

구체적 질문 예시로 RAG/SQL 에이전트 능력을 바로 보여줄 수 있는 것들.

---

## 2. D.3 — 응답 렌더러 (커밋 `27bd90d` 일부)

### 2.1 스펙 6.7 vs 현실

스펙은 4개 아티팩트 타입 지원 요구:
- `text` — 마크다운 포함 텍스트
- `plotly` — Plotly Figure JSON
- `map` — dash-leaflet (별도 타입이지만 Plotly figure 로도 가능)
- `table` — columns + data dicts

하지만 `agents/` 수정 금지. 기존 `chart_node` 는 `chart_data: str` (Plotly Figure JSON) 1개만 반환. 다른 타입은 없음. 그럼 table 은 어떻게?

### 2.2 2-path 전략

**Path A (LLM markdown)**: `synthesize` 노드가 답변 텍스트에 markdown 파이프 테이블을 자주 씀:
```
| 단지명 | 행정동 | 거래 수 |
| :--- | :--- | --- |
| 도곡렉슬 | 도곡2동 | 282 |
```

이걸 **파싱해서 `html.Table` 로 렌더**하면 agents 수정 없이 table 지원.

**Path B (sql_rows)**: `SupervisorState.sql_rows: list[dict]` 가 이미 있음 (chart_node 가 사용). 스트림 이벤트에서 이를 가로채 message dict 에 `table: list[dict]` 필드로 저장, 렌더.

두 경로 모두 구현. Path A 가 주로 작동, Path B 는 fallback.

### 2.3 markdown 파서 — 블록 + 인라인 분리

채팅 버블 안에 모든 걸 넣으면 테이블이 270px 좁은 버블에 갇힘. **테이블은 버블 밖, 별도 노드** 로 렌더해야 함.

`_parse_text_and_tables(text) -> tuple[bubble_content, tables]`:

```python
def _parse_text_and_tables(text):
    """블록 레벨 파싱 — 테이블은 별도 반환, 나머지는 bubble 안 인라인 요소."""
    lines = text.split("\n")
    bubble, tables = [], []
    pending_text, pending_list = [], []

    i = 0
    while i < len(lines):
        line = lines[i]
        # 1) Table 블록 감지
        if _is_table_row(line) and i+1 < len(lines) and _is_table_separator(lines[i+1]):
            flush_text(); flush_list()
            header = _split_cells(line)
            j = i + 2
            data_rows = []
            while j < len(lines) and _is_table_row(lines[j]):
                data_rows.append(_split_cells(lines[j])); j += 1
            tables.append(_render_md_table(header, data_rows))
            i = j
            continue
        # 2) Heading (# ~ ######)
        heading_m = _HEADING_RE.match(line)
        if heading_m:
            flush_text(); flush_list()
            level = len(heading_m.group(1))
            bubble.append(_HEADING_TAG[level](_inline_md(heading_m.group(2)), className="c-md-h"))
            ...
        # 3) List item (- 로 시작)
        list_m = _LIST_RE.match(line)
        if list_m:
            pending_list.append(list_m.group(1))
            ...
        # 4) 일반 텍스트 + <br>
        ...
    return bubble, tables
```

인라인 md: `**bold**` → `html.Strong`, `*italic*` → `html.Em`, `` `code` `` → `html.Code` (3-pass split).

### 2.4 버블 폭 가변

기존 `.c-msg .bub { max-width: 270px }` 하드코딩. 패널 크기별로 상한 재정의:

```css
.chat-panel[data-size="compact"]   .c-msg .bub { max-width: 300px; }
.chat-panel[data-size="expanded"]  .c-msg .bub { max-width: 560px; }
.chat-panel[data-size="maximized"] .c-msg .bub { max-width: 820px; }
```

(구 CSS 에 있던 `data-size="max"` 는 내가 `maximized` 로 이름 바꾼 후 매칭 실패. 정리.)

### 2.5 TermTip 렌더 버그 완전 수정

Phase 10 말미에 `display=label` 로 부분 수정했지만, `dmc.Tooltip` 이 MantineProvider 없이 작동 안 함은 여전. 사용자가 KPI 타일에서 "평당가" 등 라벨이 안 보인다고 제보.

**해결**: `dmc.Tooltip` 제거 → **native `title` 속성** + `html.Span`:

```python
def TermTip(term_key, display=None):
    term = GLOSSARY[term_key]
    return html.Span(
        display or term["label"],
        title=term["short"],       # 브라우저 기본 hover tooltip
        className="term-tip-target",
    )
```

CSS `border-bottom: 1px dotted` 로 용어임을 시각 표시. 브라우저 native 툴팁은 지연이 있고 스타일링 제약이 있지만 **무조건 동작**.

테스트도 업데이트:
```python
def test_term_tip_uses_short_as_title():
    assert TermTip("평당가").title == GLOSSARY["평당가"]["short"]
```

---

## 3. 채팅 ↔ 페이지 분리 (사용자 핵심 결정)

### 3.1 배경

기존 `_chat_invoke` 는 사이드바 State 7개 (`f-sido / f-sgg / f-area / f-deal / f-period` 등) 를 읽어 프롬프트에 `(현재 조회: 서울 · 매매 · 36개월)` 로 주입. 의도는 "사용자 편의 컨텍스트".

### 3.2 사용자 제보 버그

"전세 거래된 아파트는 없어?" 질의. LLM 응답: *"DB 는 '매매' 거래 내역을 중심으로 조회되고 있어 전세 계약 건은 표 형태로 제공해 드리지 못하는 점 양해 부탁드립니다."*

`rt_rent` 테이블은 존재하고 sql_agent 도 스키마에 인지하고 있음. 그런데 왜?

**원인 진단**: 컨텍스트 라인 `(현재 조회: ... · 매매 · ...)` 가 LLM 을 `rt_trade` 쪽으로 강하게 편향. 사이드바 f-deal=sale 이었기 때문.

### 3.3 첫 시도 — 키워드 감지 workaround

```python
user_mentions_rent = any(k in user_msg for k in ("전세", "월세", "임대", "보증금"))
if user_mentions_rent:
    ctx_line = f"(현재 지역: {scope} · 면적 {area} · 최근 {period}개월 · 사용자가 전월세 명시)"
else:
    ctx_line = f"(현재 조회: {scope} · {DEAL_LABELS.get(deal)} · {area} · 최근 {period}개월)"
```

### 3.4 사용자의 명료한 지시

> "채팅 서비스의 범위는 조건필터링은 물론 다른 페이지의 설정(조건)과 무관하게 DB 전체를 커버해야 함."

workaround 로 때우지 말고 **컨텍스트 주입 자체를 제거**하라는 원칙 선언.

### 3.5 최종 해결

```python
@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-busy", "data", allow_duplicate=True),
    Input("chat-busy", "data"),
    State("chat-msgs", "data"),
    State("chat-thread", "data"),
    # f-* States 전부 제거
    ...
)
def _chat_invoke(busy, msgs, thread):
    ...
    prompt = user_msg   # 사용자 질문만 그대로 전달
```

헤더 scope 배지도 `"실시간 · DB 전체"` 고정.

교재 포인트: **"편의 컨텍스트 주입"** 은 양날의 검. UI 상태를 암묵적으로 prompt 에 섞으면 사용자 인지 범위 밖의 영향이 발생. **명시적 질문 의도 > 암묵적 UI 상태**. 이는 D.2 (페이지 상태 → chat-context store 주입) 전체를 스킵한 이유와도 일치.

---

## 4. 장시간 질의 중단 (background callback + diskcache)

### 4.1 사용자 제보

- 질의 응답이 오래 걸림 (30초+)
- 중단 수단 없음

### 4.2 구조

Dash 의 일반 callback 은 request-response 단일 스레드. 실행 중 cancel 할 방법이 없음. **Background callback** (`background=True`) 이 정답:

```python
@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    ...
    background=True,
    cancel=[Input("chat-cancel", "n_clicks")],
    running=[
        (Output("chat-send", "style"), {"display": "none"}, {}),
        (Output("chat-cancel", "style"), {"display": "flex"}, {"display": "none"}),
        (Output("chat-input", "disabled"), True, False),
    ],
    prevent_initial_call=True,
)
def _chat_invoke(busy, msgs, thread):
    ...
```

- `background=True` — 별도 worker 에서 실행
- `cancel=[...]` — 해당 Input 트리거 시 background 작업 즉시 종료
- `running=[...]` — 실행 전/중/후 UI 상태 토글 (send → cancel 버튼 전환, 입력창 잠금)

Background manager 필요:
```python
import diskcache
from dash import DiskcacheManager

_cache = diskcache.Cache("./.cache/dash_bg")
background_manager = DiskcacheManager(_cache)
app = Dash(..., background_callback_manager=background_manager)
```

`.cache/` 는 `.gitignore` 에 추가. 개발 중엔 자동 생성됨.

### 4.3 cleanup callback

Cancel 시 `running` 이 UI 를 되돌리지만 `chat-msgs` 의 `typing` 플레이스홀더는 그대로 남음 (background callback 의 output 은 cancel 시 무효). 별도 cleanup 필요:

```python
@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-busy", "data", allow_duplicate=True),
    Input("chat-cancel", "n_clicks"),
    State("chat-msgs", "data"),
    prevent_initial_call=True,
)
def _chat_cancel(n, msgs):
    msgs = list(msgs or [])
    if msgs and msgs[-1].get("kind") == "typing":
        msgs = msgs[:-1] + [{"role": "sys", "kind": "answer", "text": "*(사용자가 중단함)*"}]
    return msgs, False
```

### 4.4 Callback 시그니처 변경 후 새로고침 필요

**사용자 보고**: "전세 거래된 아파트는 없어?" 질의 후 무한 대기. 서버 로그에 `CallbackException: Inputs do not match callback definition`.

원인: 내가 `_chat_invoke` 의 States 를 제거(§3.5)했는데 브라우저에 **구 JS 번들이 캐시**되어 있어 여전히 옛 States 를 보냄. 미스매치 → 500 → 클라이언트 무한 대기.

**해결**: `Ctrl+Shift+R` 강제 새로고침. 구조적 버그는 아니고 dev 환경의 일시 이슈. 배포 시 JS 번들 해시가 바뀌면 자동 해결.

---

## 5. PDF 업로드 (커밋 `e7018c7`)

### 5.1 경로 설계

스펙 7장: 업로드 → 파싱 → 청킹 → 임베딩 → PGVector 적재. 진입점은 채팅 퀵 액션 바의 📎 버튼만.

**문제**: `agents/rag_agent.py` 는 **검색 함수만** 있음 (`_search_chunks`, `run_rag`). 적재 함수가 없다. 스펙 7.3 은 "rag_agent 에 이미 구현되어 있으니 호출만 하라" 고 가정하지만 실제로는 없음.

**결정**: `pipeline/ingest_pdf.py` 를 **신규 작성**. `agents/config.get_vector_store()` 만 재사용 (수정 없이 호출). Vector store 인스턴스의 `.add_documents(list[Document])` 는 langchain 표준 API.

### 5.2 `pipeline/ingest_pdf.py`

```python
import fitz  # PyMuPDF
from langchain_core.documents import Document
from agents.config import get_vector_store

_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 150
_BREAKPOINTS = ("\n\n", "\n", ". ", "。", "! ", "? ", " ")

def _split_text(text, chunk_size=_CHUNK_SIZE, overlap=_CHUNK_OVERLAP):
    """문단/문장 경계 우선 청킹. langchain 의존 없이."""
    if len(text) <= chunk_size: return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # 가장 뒤쪽 경계를 찾아 끊기
            best = -1
            for sep in _BREAKPOINTS:
                idx = text.rfind(sep, start, end)
                if idx > best: best = idx + len(sep)
            if best > start: end = best
        chunks.append(text[start:end].strip())
        if end >= len(text): break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]

def ingest_pdf(path, source_name=None) -> IngestResult:
    doc = fitz.open(str(path))
    page_texts = [doc[i].get_text() for i in range(doc.page_count)]
    doc.close()

    docs = []
    for page_idx, page_text in enumerate(page_texts):
        for chunk in _split_text(page_text):
            docs.append(Document(
                page_content=chunk,
                metadata={"source": source_name or path.name, "page": page_idx + 1, "uploaded_at": ...},
            ))

    if docs:
        get_vector_store().add_documents(docs)

    return IngestResult(source=..., pages=len(page_texts), chunks=len(docs), uploaded_at=...)
```

**RecursiveCharacterTextSplitter 미사용 이유**: langchain 의존 경로를 하나 더 두지 않기 위함. `_BREAKPOINTS` 커스텀으로 한국어 문장 경계(`。`) 도 추가 가능. 20줄이면 충분.

### 5.3 Upload 콜백

`dcc.Upload` 를 퀵 액션 바에 추가. base64 payload 를 디코딩 후 저장·적재:

```python
@callback(
    Output("chat-msgs", "data", allow_duplicate=True),
    Output("chat-upload-history", "data", allow_duplicate=True),
    Output("chat-upload-count", "children"),
    Output("chat-upload-status", "children"),
    Output("chat-upload", "contents"),  # 재업로드 가능하도록 None 으로 리셋
    Input("chat-upload", "contents"),
    State("chat-upload", "filename"), ...,
    background=True,
    running=[
        (Output("chat-upload", "disable_click"), True, False),
        (Output("chat-upload-status", "children"), "처리 중… (파싱 · 임베딩)", ""),
    ],
    prevent_initial_call=True,
)
def _on_upload(contents, filename, msgs, history):
    ...
    # 검증 3단계:
    # 1) base64 디코딩 실패 → 실패 메시지
    # 2) len > 50MB → 크기 초과 메시지
    # 3) !startswith(b"%PDF") → 매직 바이트 불일치 메시지
    ...
    target = Path("uploads") / _safe_filename(filename)
    target.write_bytes(file_bytes)
    result = ingest_pdf(target, source_name=_safe_filename(filename))
    ...
    # 완료 메시지 + history append
```

검증 3단계는 스펙 7.5 그대로. `_safe_filename` 은 경로 구분자 / 특수문자를 `_` 치환.

### 5.4 업로드 목록 drawer

스펙 7.4 는 `dmc.Drawer` 권장. MantineProvider 의존 회피를 위해 **`html.Div` + CSS transform 기반 간이 drawer**:

```css
.uploads-drawer {
    position: absolute; right: 0; top: 96px; bottom: 0;
    width: 300px; z-index: 10;
    transition: transform 200ms ease-out;
}
.uploads-drawer.hidden { transform: translateX(100%); pointer-events: none; }
```

className toggle 로 open/close. 업로드 이력 `chat-upload-history` store 를 iterate 해 파일명·페이지·청크·시각 표시.

**삭제 기능 미구현**: 스펙도 "rag_agent 에 삭제 API 가 있으면" 이라는 조건부. agents 수정 금지 + langchain PGVector 의 delete_by_metadata 가 까다로워 이번 Phase 에선 제외.

---

## 6. 컴포넌트 구조 최종

```
dash_app/components/chat_panel/
├── __init__.py
├── layout.py              # chat_components() — Section + stores
├── sizes.py               # SIZE_MODES + next_mode_up/down
├── callbacks.py           # size transition + submit_send/chip + invoke + render
└── upload_callbacks.py    # dcc.Upload handler + drawer toggle + list render
```

`app.py` 에서:
```python
from dash_app.components.chat_panel import callbacks as _chat_cb  # noqa: F401
from dash_app.components.chat_panel import upload_callbacks as _chat_upload  # noqa: F401
```

두 모듈을 side-effect import 로 등록.

---

## 7. 코드 변경 규모

| 지표 | 값 |
|---|---:|
| 신규 파일 | 3 (`sizes.py`, `upload_callbacks.py`, `pipeline/ingest_pdf.py`) |
| 수정 파일 | 5 (layout, callbacks, app, chat_enter.js, kit_dashboard.css) |
| 추가 의존성 | `diskcache` (1 패키지) |
| 테스트 | 47개 (변화 없음 — 채팅 E2E 는 Phase E 로 연기) |

---

## 8. 남은 과제

- **D.2 (컨텍스트 주입)** — 스킵. 사용자가 의도적으로 제거 결정.
- **D.5 (토큰 스트리밍)** — 스킵. 중단 버튼으로 대체.
- **업로드 파일 삭제 UI** — rag_agent 에 삭제 API 가 없어 보류.

---

## 9. 교재 포인트 요약

1. **`data-size` 속성 + CSS 분기** — 하나의 컴포넌트로 4가지 시각 상태를 관리. 클래스명 대신 속성을 써 Dash callback 에서 targeting 쉽게.
2. **dash_clientside.set_props** 로 JS → Store 역방향 전달. ESC 같은 키 이벤트 처리 패턴.
3. **pattern-matching ID + 초기 렌더 오트리거** — `any(n_clicks or [])` 가드 필수.
4. **컨텍스트 주입의 trade-off** — UI 편의 vs 사용자 제어 범위. 명시 > 암묵.
5. **Background callback + diskcache** — 장시간 작업 + 중단 가능한 Dash 패턴.
6. **LLM 의 markdown 테이블 파싱** 으로 구조화 데이터 없이도 테이블 UI 실현.
7. **native title vs Mantine Tooltip** — Provider 가 필요한 외부 컴포넌트는 앱 shell 설정과 충돌 주의.
8. **langchain PGVector + PyMuPDF** 로 완전 자체 RAG 적재 파이프라인 — `.add_documents(list[Document])` 표준 API 만 알면 충분.
