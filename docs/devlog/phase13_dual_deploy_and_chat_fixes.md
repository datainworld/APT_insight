# Phase 13: Dash + Chainlit 동시 배포 + 채팅 보완

> 날짜: 2026-04-23
> 커밋: `07ee560` · `caf557e` · `c95795c`
> 엔드포인트: Dash `https://apt.deepdata.kr/` · Chainlit `http://187.77.150.150:8000/`

## 목표

1. **Dash 채팅 세션 멀티턴 메모리 복원** — Chainlit 버전엔 있었으나 Dash 에선 이어말하기가 안 됨
2. **법정동/행정동 괴리 흡수** — 사용자가 "망원동" 으로 말해도 DB 의 "망원1동", "망원2동" 까지 검색되도록
3. **Dash 앱 프로덕션 배포** — 기존 Chainlit 만 돌던 VPS 에 Dash 병행 운영, Dash 를 주 엔드포인트로 승격

---

## 1. 채팅 메모리 복원

### 1.1 증상

Dash 채팅에서 "강남구 시세" → "거기 전세는?" 식으로 이어말하기가 안 됐음. 매 턴 첫 턴처럼 처리. Chainlit 에선 `on_chat_start` 에서 `InMemorySaver` + `thread_id` 로 정상 작동.

### 1.2 근본 원인

[dash_app/app.py:45-46](../../dash_app/app.py#L45-L46) 가 `DiskcacheManager` 로 background callback 을 구성한다:

```python
_cache = diskcache.Cache("./.cache/dash_bg")
background_manager = DiskcacheManager(_cache)
```

그리고 [components/chat_panel/callbacks.py](../../dash_app/components/chat_panel/callbacks.py) 의 `_chat_invoke` 가 `background=True`. 문제:

- `DiskcacheManager` 는 background callback 실행을 **별도 프로세스**에 위임 (multiprocess 기반).
- 모듈 레벨 `_graph_singleton` + `InMemorySaver()` 가 **매 호출마다 새 프로세스에서 재생성**.
- `thread_id` 가 일치해도 그 스레드의 체크포인트가 새 프로세스의 메모리에 없음 → 멀티턴 문맥 유실.

Chainlit 은 단일 asyncio 프로세스 + `cl.user_session` 이라 동일 구조가 그냥 작동.

### 1.3 해결 — 메시지 주입 방식

체크포인터를 PostgresSaver 로 격상하는 대신, **`chat-msgs` store 의 이력을 graph 입력 `messages` 로 매 턴 직접 주입**:

[dash_app/components/chat_panel/callbacks.py](../../dash_app/components/chat_panel/callbacks.py) 에 `_build_message_history()` 추가:

```python
def _build_message_history(msgs: list) -> list:
    from langchain_core.messages import AIMessage, HumanMessage
    history: list = []
    for m in msgs or []:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        role = m.get("role")
        kind = m.get("kind")
        if role == "user":
            history.append(HumanMessage(content=text))
        elif role == "sys" and kind == "answer":
            history.append(AIMessage(content=text))
    return history
```

`_chat_invoke` 에서 `[HumanMessage(content=prompt)]` 대신 `_build_message_history(msgs[:-1])` 를 `messages` 로 주입. [agents/graph.py:149](../../agents/graph.py#L149) 의 `recent = state["messages"][-8:]` 슬라이싱이 있어 컨텍스트는 자동으로 바운드됨.

**트레이드오프**: 브라우저 새로고침 시 이력 휘발(`chat-msgs` 가 `storage_type=memory`). 세션 유지가 더 필요하면 `storage_type="session"` 으로 올리면 됨. 영구 저장은 PostgresSaver 도입이 정석.

---

## 2. 법정동/행정동 OR 룰

### 2.1 증상

"망원동" 으로 질의 → SQL Agent 가 `WHERE admin_dong = '망원동'` 생성 → 0건. DB 에는 행정동인 '망원1동', '망원2동' 만 존재.

### 2.2 구조 이해

- `rt_complex.admin_dong` = 카카오 `region_3depth_name` = **행정동** ('망원1동','망원2동')
- `rt_complex.jibun_address` = [pipeline/collect_rt.py:181](../../pipeline/collect_rt.py#L181) 에서 `{umdNm} {jibun}` 로 생성 — `umdNm` 은 **법정동** ('망원동 123-4')
- `nv_complex.dong_name` = 동일하게 카카오 admin_dong (`_get_admin_dong` 으로 재작성)

### 2.3 해결 — SQL 프롬프트에 OR 룰 추가

[agents/sql_agent.py](../../agents/sql_agent.py) 의 `GENERATE_PROMPT` 에 전용 섹션 삽입:

```markdown
## 동(洞) 필터 — 법정동/행정동 괴리 흡수 (중요)

- **rt_* 테이블**:
  `(rt_complex.admin_dong LIKE '<동>%' OR rt_complex.jibun_address LIKE '<동>%')`
  - jibun_address 는 '<법정동> <지번>' 형식이라 법정동명으로 시작.
- **nv_* 테이블** (nv_complex.dong_name 만 존재):
  `nv_complex.dong_name LIKE '<동>%'`
  - 대부분 법정동은 행정동 이름 접두사 ('망원동'→'망원1동').
- 행정동 전체명 ('망원1동') 명시 시 그 문자열 그대로 `LIKE '망원1동%'`.
```

**한계**: 접두사가 다른 예외('신수동' ↔ 행정동 '용강동') 는 nv_* 쿼리에서 여전히 놓침. 100% 보장이 필요하면 법정동 ↔ 행정동 매핑 테이블을 적재해야 함. 일반적 쿼리는 이 룰로 충분.

---

## 3. Dash + Chainlit 동시 배포

### 3.1 계획 (C:\Users\iyagi\.claude\plans\flickering-tickling-graham.md)

기존 상태 (Phase 5):
- Dokploy Application 1개 (Chainlit) → Traefik 80 으로만 노출
- `docker-compose.yml` 엔 `dashboard` 서비스가 정의돼 있었지만 Dokploy 에 등록 안 됨

목표: **Dash 메인(80) + Chainlit 보조(8000)**. 초기에 "Raw 포트 노출" + "gunicorn" + "Chainlit 8000 유지" 를 선택.

### 3.2 코드 변경

| 파일 | 변경 |
|------|------|
| `pyproject.toml` | `gunicorn`, `multiprocess` 의존성 추가 |
| `docker-compose.yml` | dashboard 서비스 command → gunicorn, `uploads` 볼륨 공유 |
| `Dockerfile` | (기존 세션 전 변경) `dash_app` COPY + `EXPOSE 8050` |

### 3.3 배포 과정의 4 가지 장애

#### ① Dokploy Command/Args 파싱

초기 시도 — Command 에 `gunicorn dash_app.app:server -b 0.0.0.0:8050 -w 2 --timeout 120` 한 줄 입력:
```
ModuleNotFoundError: No module named 'gunicorn dash_app'
```
Dokploy 는 Command 를 **쉘 파싱 없이 단일 argv 요소**로 전달 → gunicorn 이 app 스펙으로 착각.

Args 분리 시도:
```
gunicorn: error: argument -w/--workers: invalid int value: ' '
```
Args 항목 중 하나에 공백 혼입으로 `2` 대신 `' '` 가 전달.

**해결**: `sh -c` 래퍼.
- Command: `sh`
- Args: `-c`, `exec gunicorn dash_app.app:server -b 0.0.0.0:8050 -w 2 --timeout 120`

Args 2개뿐이라 공백 혼입 여지 최소. `exec` 는 쉘 프로세스를 gunicorn 으로 교체해 신호 전파 정상화.

#### ② multiprocess 의존성 누락

`dash[diskcache]` extra 가 `diskcache` + **`multiprocess`** 를 함께 설치. 메인 deps 에 `diskcache` 만 있어서 기동 시:
```
ImportError: DiskcacheManager requires extra dependencies
```

`pyproject.toml` 에 `multiprocess` 명시적으로 추가 ([caf557e](../../.git/logs/refs/heads/main)).

#### ③ import-time 쿼리의 미존재 테이블 참조

다음 에러로 워커 부팅 실패:
```
psycopg.errors.UndefinedTable: relation "news_articles" does not exist
```

[dash_app/pages/about.py:375](../../dash_app/pages/about.py#L375) 의 `layout = html.Main(...)` 이 모듈 임포트 시점에 `_section_data_sources() → get_coverage()` 를 호출. 해당 SQL 이 `news_articles` 를 조회하지만 `CLAUDE.md` 에 명시된 대로 이 테이블은 **의도적으로 존재하지 않음** (뉴스는 News Agent 가 실시간 조회).

**해결**: [dash_app/queries/coverage_queries.py](../../dash_app/queries/coverage_queries.py) 에서 news_articles COUNT 제거, [dash_app/pages/about.py](../../dash_app/pages/about.py) 에서 '뉴스 기사' stat 표시 제거 ([c95795c](../../.git/logs/refs/heads/main)).

home.py 의 뉴스 쿼리는 callback 런타임 + try/except 로 이미 graceful — 수정 불필요.

**교훈**: Dash `use_pages=True` 에서 `layout` 을 모듈 탑레벨 변수로 선언하면 앱 임포트 시 DB 쿼리가 실행됨. 무거운 초기화나 DB 접근은 callback 안으로 옮기거나 lazy evaluation (함수형 `def layout()`) 권장.

#### ④ Hostinger 외부 방화벽

Chainlit 에 `--publish-add 8000:8000` 으로 포트 노출 → VPS 내부 (`127.0.0.1:8000`) 는 HTTP 200 이지만 외부에서는 timeout. UFW 는 `inactive` 였고 Hostinger **패널 레벨 방화벽**이 차단. Phase 5 에서도 같은 이슈 겪은 바 있음. 사용자가 Hostinger 콘솔에서 TCP 8000 inbound Accept 규칙 추가 → 즉시 HTTP 200 확인.

### 3.4 Traefik 도메인 스왑 (계획 변경)

초기 계획: `187.77.150.150` IP + port 80 으로 Dokploy Domain 등록. 사용자가 실제로는 `apt.deepdata.kr` 도메인 + HTTPS(Let's Encrypt) 로 설정 — **원래 계획보다 개선**. 결과:

- `http://apt.deepdata.kr/` → 301 → `https://apt.deepdata.kr/` (Dash)
- `http://187.77.150.150:8000/` → Chainlit (직접 publish)

`/etc/dokploy/traefik/dynamic/apttransactioninsight-aptdash-xtddxs.yml` 에 자동 생성된 라우터·서비스·TLS certResolver 설정이 이를 처리.

IP 로만 접근 시도하면 Traefik 이 `Host: apt.deepdata.kr` 룰만 갖고 있어서 404 — 도메인 경유 필요.

---

## 4. 최종 상태

| 경로 | 서비스 | 노출 방식 |
|------|--------|-----------|
| `https://apt.deepdata.kr/` | Dash (gunicorn, workers=2) | Traefik + Let's Encrypt |
| `http://187.77.150.150:8000/` | Chainlit (uvicorn) | Docker Swarm port publish |

**공유 자원**:
- DB: `apttransactioninsight-aptdb-vrkyfm` (PostgreSQL 18 + pgvector)
- `uploads` 볼륨: 두 서비스에 동일 마운트 → PDF 업로드·검색 공유
- `.env` Environment: Dokploy Environment 탭 (Dash 앱은 Chainlit 앱의 변수 그대로 복사)

**Dokploy 앱 구성**:
- `apt-insight` (Chainlit) — Domains 비움, 포트 8000 publish
- `apt-dash` (Dash) — Domains 에 `apt.deepdata.kr` + HTTPS

---

## 5. 주요 교훈

1. **Dash background callback + InMemorySaver 는 서로 상극**. 프로세스 격리로 체크포인터 무용. Dash 환경에선 messages 주입 또는 Postgres 계열 체크포인터가 정답.
2. **Dokploy Command 필드는 쉘 파싱 없음**. 쉘 기능 필요하면 `sh -c` 래퍼.
3. **Dash `layout` 모듈 변수는 임포트 시 즉시 평가됨**. DB 쿼리는 callback 으로 옮기거나 함수형 layout 으로.
4. **Hostinger VPS 는 호스팅사 패널 방화벽이 따로 있음**. UFW 만 보면 안 됨.
5. **Traefik 라우팅은 Host 헤더 기반**. IP 로만 접근 시도하면 도메인 라우터가 매칭 안 됨 — 도메인 이용이 정석.
