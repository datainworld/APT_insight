# Phase 8: 성능 최적화 및 운영 정리

> 날짜: 2026-04-19

## 목표

Phase 7 로 답변 품질이 안정화된 후 실사용하니 두 종류의 문제가 드러났다.

1. **응답 속도**: 단순 질의도 60~80초 소요. 트레이스를 보니 SYNTHESIS 모델·파이프라인 구조 양쪽에 병목 존재.
2. **데이터 무결성 미세 이슈**: 네이버 매물의 `first_seen_date`/`last_seen_date` 가 실제 관측일보다 하루 뒤처진 채 저장되고 있었다 (`confirm_date > last_seen_date` 인 12,738건으로 드러남).

Phase 8 은 이 두 문제를 추적하며, 동시에 **모델·질의 조합을 상시 비교할 수 있는 벤치마크 모듈**을 도입한다.

---

## 1. Remote 배포 및 DB 동기화

Phase 6~7 누적 변경 사항을 Remote 에 반영하고 검증 일관성을 위해 Remote DB 를 Local 로 받았다.

### 배포

커밋 두 건으로 정리 (`eb1e83a`, `89c20ec`).

Dokploy `Deploy` 버튼 1차 실행 시 빌드 실패:
```
COPY data/maps/ ./assets/maps/
ERROR: "/data/maps": not found
```

원인: `.gitignore` 가 `data/` 전체를 배제해서 원격 저장소에 `metro_sgg.geojson` 이 없었다. Dockerfile 의 `COPY data/maps/` 는 로컬에만 파일이 있는 상태에서 작성돼 원격 빌드에서만 깨짐.

**수정**: `.gitignore` 를 `data/*` + `!data/maps/` 로 변경하여 정적 지도 자원만 추적하고 런타임 데이터는 그대로 배제.

### Remote → Local DB 동기화

Phase 7 devlog 에서 정리한 패턴을 그대로 사용. SSH → `docker exec pg_dump` → scp → `pg_restore` 4단계 대신 SSH 스트림으로 한 번에 덤프:

```bash
ssh deepdata 'CID=$(docker ps --filter name=aptdb --format "{{.ID}}" | head -1); \
    docker exec -i $CID pg_dump -U postgres -d apt_insight -Fc' \
    > data/backups/backup_remote_20260419.dump

pg_restore -h localhost -U postgres -d apt_insight \
    --clean --if-exists --no-owner --no-privileges \
    data/backups/backup_remote_20260419.dump
```

PG 17 로컬 ↔ PG 18 원격, `--clean --if-exists` 로 기존 테이블 drop 후 재생성. 경고 없이 정상 복원. 결과:

| 테이블 | 건수 |
|---|---:|
| rt_complex | 15,061 |
| rt_trade | 624,590 |
| rt_rent | 1,919,417 |
| nv_complex | 22,373 |
| nv_listing | 3,702,718 |
| complex_mapping | 12,271 |

---

## 2. VPS 시간대 버그 (UTC → KST)

### 발견

`nv_listing` 무결성 검증 중 `confirm_date > last_seen_date` 인 레코드 **12,738 건**. 모두 정확히 gap=1 day.

- `last_seen_date` MAX = 2026-04-18 (어제, 파이프라인 마지막 실행일)
- `confirm_date` MAX = 2026-04-19 (오늘)

처음엔 네이버 원천 데이터의 quirk 로 의심했으나, 사용자가 "외국에 있는 서버의 시계에 맞춰서 찍힌 것 아닐까?" 로 가설 제시.

### 원인 확인

```bash
$ ssh deepdata 'timedatectl | grep Zone'
Time zone: Etc/UTC (UTC, +0000)
```

VPS·앱 컨테이너·DB 컨테이너 모두 UTC. `pipeline/utils.py:get_today_str()` 가:

```python
datetime.now().strftime("%Y%m%d")
```

로 시스템 로컬시간 (= UTC) 을 사용. Dokploy cron 이 **03:00 KST = 18:00 UTC 전날** 에 실행되므로:

- 컨테이너의 `datetime.now()` → UTC 기준 2026-04-18
- 같은 시각 네이버의 `confirm_date` (KST 기준) → 2026-04-19
- 결과: 저장된 `last_seen_date` = 2026-04-18, `confirm_date` = 2026-04-19 인 **하루 밀린** 레코드 발생

### 수정

3 가지 옵션 (컨테이너 TZ 변경 / 코드에서 KST 명시 / cron 시각 변경) 중 **코드 명시** 선택. 이유: 프로젝트가 한국 부동산 도메인이라 날짜 의미가 KST 고정이고, 배포 환경에 의존하지 않는 포터블한 해결이다.

`pipeline/utils.py` 에 `now_kst()` 헬퍼 추가:

```python
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

def now_kst() -> datetime:
    return datetime.now(KST)
```

`pipeline/` 내의 `datetime.now()` 호출 7 곳을 모두 `now_kst()` 로 교체 (collect_rt, collect_naver, update_rt_daily, update_nv_daily, run_daily).

커밋: `cf2c20a`.

### 과거 데이터 처리 (소극적 대응)

이미 저장된 12,738 건 중:
- `is_active=TRUE` 77건 → 다음 수집 시 `last_seen_date` 가 KST 오늘로 덮어써져 **자연 해소**
- `is_active=FALSE` 12,661건 → freeze 상태라 영구 잔존

일괄 백필은 하지 않기로 결정. 이유: 어느 레코드가 정확히 UTC lag 영향을 받았는지 식별할 수 있는 로그가 없고, 무작정 +1일 보정 시 정상 데이터까지 훼손할 위험. 분석 시 "2026-04-18 이전의 `first_seen_date`/`last_seen_date` 는 실제 KST 관측일보다 ±1일 오차 가능" 이라는 단서로만 다룬다.

---

## 3. 응답 지연 진단

### 로그 기반 초기 분석

단일 질의에 **~73초, LLM 호출 ~11회** 소요. 로그에서:

```
15:55:22 → 15:55:59 : 37초 단일 SYNTHESIS 호출 (gemini-3-flash-preview)
```

병목 구조:
- **SYNTHESIS 모델(`gemini-3-flash-preview`)** 이 lite 대비 **5~10배 느림**. 30초 넘는 단일 호출이 자주 발생
- SYNTHESIS 사용처 7~9곳: `query_generator` · `_rewrite_to_standalone` · `sql_agent.generate_query/check_query` (최대 5회 재시도) · `synthesize`

### LangSmith 트레이스로 정밀 분석

실제 트레이스를 확인하니 `sql_node` 가 전체의 80% 차지 (**65.4s / 81.5s**):

| 구간 | 시간 | 누적 비율 |
|---|---:|---:|
| sql_node 전체 | 65.4s | 80% |
| ├ check_query × 2 | 37.2s | 46% |
| ├ generate_query × 2 | 27.9s | 34% |
| └ run_query × 2 | 0.3s | 0.4% |
| synthesize × 2 | 9.3s | 11% |

1 차 쿼리가 check 단계에서 거부돼 1회 재시도 (`_MAX_ATTEMPTS=5` 내 정상 동작이지만 사이클 2배). synthesize 가 왜 2회 실행되는지는 별도 이슈로 식별.

---

## 4. 벤치마크 모듈 도입 (`scripts/benchmark/`)

### 설계 의도

"SYNTHESIS 모델이 진짜 품질 기여를 하는지, 그 대가의 속도 희생이 정당한지" 를 **주관이 아니라 데이터**로 판단하고자 도입. 1회성 스크립트가 아니라 **상시 사용 가능한 모듈**로 설계.

### 구조

```
scripts/benchmark/
  __init__.py
  __main__.py       # argparse CLI + Windows cp949 대응 (stdout UTF-8 강제)
  core.py           # Runner, TrialConfig, Query, RunResult, monkey-patch 헬퍼
  callbacks.py      # LatencyTracker (BaseCallbackHandler, node+model 단위 집계)
  judge.py          # LLM-as-judge (4차원 rubric: correct/complete/clarity/action)
  report.py         # trial 총합 / trial×query / trial×node 3단 집계

benchmarks/
  trials.json       # 모델 조합 (provider, model, synthesis_model 스펙)
  queries.json      # 질의 세트

data/benchmarks/
  YYYYMMDD-HHMMSS/{results.json, summary.md}
```

### 핵심 기술

**Monkey-patch 로 trial 전환**: 서브에이전트들이 노드 함수 안에서 `get_llm()` 을 매번 호출하므로, 다음 4 곳만 덮어쓰면 graph 재빌드 없이 새 모델이 적용된다:

```python
agents.config.LLM_PROVIDER
agents.config.LLM_MODEL
agents.graph.LLM_MODEL_SYNTHESIS
agents.sql_agent.LLM_MODEL_SYNTHESIS
```

**노드별 지연 추적**: LangGraph 가 callback `metadata["langgraph_node"]` 에 노드명을 넣어주므로, `BaseCallbackHandler.on_chat_model_start/end` 에서 (node, model, elapsed, tokens_in/out) 을 그대로 기록.

**Judge 격리**: judge LLM 호출 시 provider/model 을 일시 덮어쓰고 `finally` 에서 복원 → trial 상태 침범 방지.

**의존성 확장**: `pyproject.toml` 에 `langchain-anthropic`, `langchain-openai` 추가 (현재는 Gemini 만 쓰지만 Claude·OpenAI 비교 가능하도록).

### 구현 중 발견한 두 버그

1. **Unicode print 크래시** — Windows cp949 콘솔이 `summary.md` 안의 em-dash(`—`) 를 못 다뤄 `print(md)` 에서 UnicodeEncodeError. 결과 파일은 이미 저장된 뒤 발생해서 데이터 손실은 없었지만, exit code 1 로 종료. `sys.stdout.reconfigure(encoding="utf-8")` 로 해결.

2. **graph.invoke 응답이 빈 문자열** — 첫 run 에서 모든 response_len = 0. 원인: graph 의 `synthesize` 노드가 병렬 브랜치 합류 문제로 **2회 실행**되는데, 2회차가 빈 `AIMessage` 를 반환하면서 `msgs[-1]` 를 덮어썼다. 우회: `for m in reversed(msgs): if isinstance(m, AIMessage) and non-empty: return` 로 마지막 non-empty AI 메시지를 선택. (근본 원인은 §5 에서 해결)

3. **Judge 파싱 실패** — Gemini 가 `content` 를 `[{"type":"text","text":"{...JSON...}","extras":{...}}]` 리스트로 반환. 단순 `str(reply.content)` 로 감싸면 Python repr 이 돼서 JSON 파싱 실패. `agents.graph._extract_text` 재사용으로 해결.

### 측정 결과 (n=3, 질의 1개)

질의: "매매가 대비 전세가 비율이 높아서 갭투자가 용이한 행정동은 어디인가요?"

| trial | elapsed | LLM calls | judge avg (1-5) |
|---|---:|---:|---:|
| gemini-lite-only | **17.2s** | 11.3 | **2.17** |
| gemini-3-synth | 47.7s (**2.8× 느림**) | 11.0 | 1.42 |

**의외의 결과**: lite 만 써도 속도·품질 **둘 다 우위**. Phase 7 에서 "상위 모델" 가정으로 도입한 SYNTHESIS 계층이 이 프로젝트 맥락에서는 역효과.

Judge 코멘트에서 공통적으로 "전세가율 474%·178%" 같은 비정상 수치를 환각으로 지적. 이는 LLM 환각이 아니라 **실제 SQL 결과의 필터링 누락** 이라는 별도 이슈로 드러남 (§남은 이슈).

---

## 5. SYNTHESIS 롤백 (5배 속도 개선)

벤치마크 결론에 따라 `.env` 에서 `LLM_MODEL_SYNTHESIS` 제거. `shared/config.py:30` 의 `os.getenv("LLM_MODEL_SYNTHESIS", LLM_MODEL)` 폴백이 자동 동작하므로 코드 변경 불필요.

LangSmith 트레이스 재측정: **81.5s → 16.0s** (동일 질의, 5× 빠름). 비교:

| 구간 | SYNTHESIS 사용 | lite 만 | 개선 |
|---|---:|---:|---:|
| query_generator | 6.8s | 2.3s | -66% |
| sql_node | 65.4s | 5.1s | -92% |
| synthesize × 2 | 9.3s | 6.8s | -27% |
| **총** | **81.5s** | **16.0s** | **-80%** |

---

## 6. synthesize 2회 실행 수정 (graph edge 재배치)

### 원인

LangGraph 의 Pregel BSP 실행 모델은 "각 노드는 입력 엣지가 모두 준비되면 실행" 이다. `synthesize` 로 향하는 경로 길이가 불균형했다:

- `sql_node → chart_node → synthesize` (2 hop)
- `rag_node → synthesize` (1 hop)
- `news_node → synthesize` (1 hop)

Superstep 2 에서 sql/rag/news 병렬 실행. Superstep 3 에서 chart_node 와 synthesize 가 동시에 ready (rag/news 경로가 완료됐으니) — synthesize 1 차 실행 (sql_result 없이 rag+news 결과만). Superstep 4 에서 chart_node 완료 → synthesize 2 차 실행 (전체 결과 포함).

결과: LLM 2회 호출 + 토큰 낭비 + 1차 빈 출력이 마지막 메시지로 남는 부작용.

### 수정

`chart_node` 를 synthesize 의 크리티컬 패스에서 분리. 4 줄 엣지 변경:

```python
# Before
builder.add_edge("sql_node", "chart_node")
builder.add_edge("chart_node", "synthesize")   # 2 hop 경로 생성
builder.add_edge("rag_node", "synthesize")
builder.add_edge("news_node", "synthesize")

# After
builder.add_edge("sql_node", "chart_node")
builder.add_edge("sql_node", "synthesize")     # NEW: 1 hop 으로 직결
builder.add_edge("chart_node", END)            # 곁가지로 분리
builder.add_edge("rag_node", "synthesize")
builder.add_edge("news_node", "synthesize")
```

이제 sql/rag/news 모두 1 hop 으로 synthesize 에 수렴 → 합류 동기화 → synthesize **1회만 실행**. chart_node 는 synthesize 와 **병렬 실행** 되어 ~3.8s 순차 비용이 숨겨짐.

synthesize 가 `chart_data` 를 사용하지 않음을 사전 확인 (synthesize 는 sql_result/rag_result/news_result 만 참조). app.py 의 stream consumer 는 이벤트 도착 순서 무관하게 chart_data 와 final_msg 를 따로 모으므로 UI 로직 무변경.

---

## 7. news/rag 에이전트 단순화 (LLM 호출 반감)

### 발견

트레이스에서 `news_node` 가 여전히 9.25s 소요 — 내부적으로 LLM 2회 호출:

```
LLM #1 (1.40s): "search_news(질의) 를 호출해야겠다" ← 도구 선택만
tool     (2.76s): Naver API + 본문 스크래핑
LLM #2  (4.33s): 검색 결과로 요약 답변 작성
```

LLM #1 은 본질적으로 **통과 역할**:
- `query_generator` 가 이미 `news_query` 를 만들어 넘김
- agent LLM #1 은 그걸 `search_news(query)` 인자로 전달하기로 "결정"
- 관찰된 모든 trace 에서 tool 호출 횟수는 **항상 1회** → tool-using 패턴의 장점 (다중 도구 선택, 반복 호출) 을 쓰지 않음

`rag_node` 도 동일 패턴 (`create_agent(llm, [search_pdf])`).

### 수정

`create_news_agent()` / `create_rag_agent()` → 각각 `run_news(query)` / `run_rag(query)` 직접 호출 함수로 교체.

- 검색·필터링 로직은 내부 헬퍼 (`_fetch_articles`, `_search_chunks`) 로 추출
- LLM 호출은 1회: system prompt + "[질의]\n{query}\n\n[검색 결과]\n{articles}"
- 검색 결과가 없으면 LLM 호출 스킵 (고정 문자열 반환)

`graph.py` 의 `news_node` / `rag_node` 는 3줄 → 1줄로 축약:

```python
def news_node(state):
    query = state.get("news_query")
    if not query:
        return {"news_result": None}
    return {"news_result": run_news(query)}
```

### 기대 효과

- news_node: ~9s → **~4s** (LLM #1 제거, ~1.4s 절감)
- rag_node: ~7s → **~3s**
- 병렬이라 총 시간은 `max(sql, rag, news)` 지배 → **16s → ~10s** 예상
- 토큰 사용량도 비례 감소 (system prompt + LLM #1 입력 분량 절약)

**포기한 것**: 이론상의 multi-round tool-using 능력. 현재 사용 패턴에선 쓰지 않고 있어 실효 없음.

---

## 남은 이슈

1. **전세가율 > 100% 이상치** — 갭투자 질의에서 "474% / 178%" 비정상 비율이 표에 노출. SQL 결과 필터링 또는 프롬프트 단에서 100% cap 검증 필요.
2. **check_query 재시도** — SYNTHESIS 롤백으로 절대 시간은 줄었지만, generate_query→check_query 한 사이클이 여전히 2회 도는 케이스 관찰. check_query 프롬프트의 false-reject 경향 점검 필요.
3. **Dokploy 자동 배포** — 현재 Webhook URL 이 HTTP·IP·비표준포트 3가지 이유로 불안정. 안정화 시점에 Traefik 경유 HTTPS + 도메인 엔드포인트로 전환 검토.

---

## 이번 Phase 의 교훈

- **"상위 모델" 가정은 벤치해야 안다.** Phase 7 에서 품질 목적으로 도입한 SYNTHESIS 계층이 측정해보니 속도·품질 모두 역효과였다. LLM 은 자주 반직관적이다.
- **LangGraph 의 Pregel 실행 모델을 이해하면 엣지 4줄 로 2× 속도 개선이 가능하다.** 병렬 브랜치가 synthesize 에 수렴할 때 경로 길이를 맞추는 것이 핵심.
- **tool-using agent 패턴은 실제 multi-round 가 필요할 때만 쓰자.** 단일 도구·단일 호출이면 직접 함수 호출로 LLM round 1회 절약.
- **타임존은 환경이 아니라 코드에 명시해야 안전하다.** VPS 의 기본 TZ 는 리전마다 다르고, 컨테이너 재빌드 시 초기화된다.
- **재사용 가능한 벤치마크 모듈을 한 번 만들어두면, 이후 모든 최적화 의사결정이 데이터 기반이 된다.** 앞으로 모델 변경·프롬프트 수정 시마다 "감" 아닌 수치로 판단 가능.
