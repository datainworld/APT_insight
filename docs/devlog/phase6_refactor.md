# Phase 6: 파이프라인 리팩토링 + 인프라 정리

> 날짜: 2026-04-17

## 목표

Phase 1~5에서 동작하는 시스템을 구축했으나, **교재 '공공데이터 활용 with AI' advance**의 pages 10~19 설명과 실제 코드가 어긋나는 부분이 많았다. 교재와 코드를 1:1 정합하도록 파이프라인을 재구성하고, 동시에 운영을 위한 인프라 정리(서비스 통합, 도메인 연결, 멀티턴 메모리)를 수행한다.

## 주요 변경 6건

1. 파이프라인 리팩토링 (교재 10~19장 정렬)
2. DB 스키마 마이그레이션 (자연키 UNIQUE + FK 복구)
3. Remote 운영 전환 (수동 run_daily → Dokploy Schedule)
4. apt-pipeline 서비스 제거 (서비스 통합)
5. 멀티턴 대화 메모리 (레벨 A)
6. 도메인 연결 (apt.deepdata.kr)

---

## 1. 파이프라인 리팩토링 — 교재 장별 파일 정렬

### 문제 진단

Phase 1에서 만든 `pipeline/`은 한 파일에 여러 책임이 섞여 교재 설명과 대응이 어려웠다.

| 문제 | 위치 | 설명 |
|------|------|------|
| TRUNCATE + INSERT | `update_daily.py` | 교재 17장 "INSERT OR IGNORE 누적 운영"과 반대 방향. 매일 전체 삭제 후 재적재 |
| 세션·adaptive delay가 collect_naver 내부 | `collect_naver.py` (860줄) | 일일 갱신 모듈이 **상수 덮어쓰기**라는 우회로만 재사용 가능 |
| diff_listings 순수함수 부재 | `collect_naver.py` | 교재 18장의 {new, changed, kept, closed} 분류가 루프에 매립 |
| run_daily 오케스트레이터 없음 | — | 교재 19장의 JSON 리포트·exit code 구조 없음 |
| 매핑(14장)·일일갱신(18장) 혼재 | `collect_naver.py` | `full`/`daily`/`mapping` 서브커맨드로 한 파일에 묶임 |

### 재설계 방향

교재의 장 구조와 1:1 대응하도록 **공통 모듈 추출 + 장별 파일 분리**:

| 파일 | 교재 장 | 역할 |
|------|---------|------|
| `pipeline/naver_session.py` | 10 | curl_cffi 세션, adaptive delay, `request_json` 공용 |
| `pipeline/schemas.py` | 17 보조 | 국토부 API → rt_trade/rt_rent 변환 공통 |
| `pipeline/build_mapping.py` | 14 | rt_complex ↔ nv_complex 2단계 스코어링 매핑 |
| `pipeline/update_rt_daily.py` | 17 | 3개월 슬라이딩 윈도우 + `ON CONFLICT DO NOTHING` + 36개월 cleanup |
| `pipeline/update_nv_daily.py` | 18 | `diff_listings` 순수함수 + 생명주기 필드 관리 |
| `pipeline/run_daily.py` | 19 | RT → NV 순차, 에러 격리, JSON 리포트 |
| `pipeline/collect_naver.py` | 10~13 | **`full` 모드만** 유지 (초기 수집). `daily`·`mapping` 제거 |

### 핵심 변경: `update_rt_daily`의 누적 운영

**Before (update_daily.py)**:

```python
conn.execute(text("TRUNCATE rt_trade;"))
for chunk in pd.read_csv(file_trade, chunksize=50000):
    chunk.to_sql("rt_trade", conn, if_exists="append")
```

매일 전체 삭제 후 재적재. 36개월 마스터 CSV에 의존.

**After (update_rt_daily.py)**:

```python
conn.execute(text("""
    INSERT INTO rt_trade (apt_id, apartment_name, deal_date, deal_amount, ...)
    SELECT ... FROM rt_trade_staging s
    WHERE EXISTS (SELECT 1 FROM rt_complex c WHERE c.apt_id = s.apt_id)
    ON CONFLICT ON CONSTRAINT rt_trade_natural_uq DO NOTHING;
"""))
```

3개월 새 데이터만 UPSERT. 36개월 초과는 `cleanup_old_data`로 별도 정리. **교재 17장 "추가형 · 신고 지연 대응" 패러다임 구현**.

### 핵심 변경: `diff_listings` 순수함수 (18장)

교재 18장의 핵심 개념. {new, changed, kept, closed} 분류와 생명주기 필드를 **DB·IO 없는 순수함수**로 분리:

```python
def diff_listings(yesterday_dict: dict, today_list: list, today_str: str
                  ) -> tuple[list, dict]:
    counts = {"new": 0, "changed": 0, "kept": 0, "closed": 0}
    result = []
    seen = set()

    for row in today_list:
        ano = str(row["article_no"])
        seen.add(ano)
        new_row = dict(row)
        if ano in yesterday_dict:
            prev = yesterday_dict[ano]
            # 불변 필드 보존
            new_row["first_seen_date"] = prev.get("first_seen_date") or today_str
            new_row["initial_price"] = prev.get("initial_price") or row["current_price"]
            # 매일 갱신
            new_row["last_seen_date"] = today_str
            new_row["is_active"] = True
            counts["changed" if row["current_price"] != prev.get("current_price") else "kept"] += 1
        else:
            new_row["first_seen_date"] = today_str
            new_row["last_seen_date"] = today_str
            new_row["initial_price"] = row["current_price"]
            new_row["is_active"] = True
            counts["new"] += 1
        result.append(new_row)

    # 오늘 안 보인 어제 활성 매물 → is_active=False
    for ano, prev in yesterday_dict.items():
        if ano not in seen:
            closed = dict(prev)
            closed["is_active"] = False
            closed["last_seen_date"] = today_str
            counts["closed"] += 1
            result.append(closed)

    return result, counts
```

순수함수라 **단위 테스트**가 가능하다. DB/API 없이 4가지 분기를 검증할 수 있어 교재 독자에게 설명하기도 쉽다.

### run_daily 오케스트레이터 (19장)

```python
def main() -> None:
    started_at = datetime.now()
    report = {"date": started_at.strftime("%Y-%m-%d"), ...}

    try: report["rt"] = update_rt()   # 국토부
    except Exception as e: report["rt"] = {"status": "error", "message": str(e)}

    try: report["nv"] = update_nv()   # 네이버
    except Exception as e: report["nv"] = {"status": "error", "message": str(e)}

    # 한쪽 실패 시 status="partial"
    report["status"] = ("success" if 두쪽 OK else
                        "partial" if 한쪽 OK else "error")

    (BASE_DIR / "data" / "reports" / f"{date}.json").write_text(json.dumps(report))
    sys.exit(0 if report["status"] == "success" else 1)
```

- 에러 격리 (한쪽 실패해도 다른 쪽은 계속)
- `data/reports/YYYY-MM-DD.json` 기계가독 리포트
- exit code로 스케줄러가 상태 판정 가능

### 커밋 이력

```
14bed7e refactor(pipeline): extract naver_session and schemas modules
32c2cf7 feat(pipeline): build_mapping module (textbook ch.14)
e67ae09 refactor(collect_naver): remove session/mapping, keep full mode only
e6073db feat(pipeline): update_rt_daily + natural UNIQUE constraints (ch.17)
5fce208 feat(pipeline): update_nv_daily + diff_listings pure function (ch.18)
9e8cf7b feat(pipeline): run_daily orchestrator + JSON report (ch.19); drop update_daily
```

의도적으로 **8개 작은 커밋**으로 나눴다. `git bisect`과 교재의 장별 설명에 맞추기 위함.

---

## 2. DB 스키마 마이그레이션

### 왜 UNIQUE 제약이 필요한가

교재 17장의 핵심은 `INSERT OR IGNORE` (SQLite) 또는 `ON CONFLICT DO NOTHING` (PostgreSQL) 로 **중복 회피 누적**. 이를 위해 `rt_trade`/`rt_rent`에 **자연키 UNIQUE 제약**이 있어야 한다.

자연키 설계:
- `rt_trade`: `(apt_id, deal_date, deal_amount, exclusive_area, floor)`
- `rt_rent`: `(apt_id, deal_date, deposit, monthly_rent, exclusive_area, floor)`

### `migrate_unique_constraints.py` (1회성)

**시행착오**: 처음엔 자기조인으로 중복 제거했다.

```sql
-- O(N²), 실제로 14분 후에도 끝나지 않음
DELETE FROM rt_rent a USING rt_rent b
WHERE a.id > b.id
  AND a.apt_id = b.apt_id
  AND a.deal_date IS NOT DISTINCT FROM b.deal_date
  ...
```

rt_rent 220만 행에서 `a × b` 카테시안이 너무 무겁다.

**해결**: CTID + ROW_NUMBER (O(N log N)):

```sql
DELETE FROM rt_rent
WHERE ctid IN (
    SELECT ctid FROM (
        SELECT ctid, ROW_NUMBER() OVER (
            PARTITION BY apt_id, deal_date, deposit, monthly_rent, exclusive_area, floor
            ORDER BY id
        ) AS rn FROM rt_rent
    ) t WHERE rn > 1
);
```

수 초 내 완료. PARTITION BY가 NULL을 같은 그룹으로 묶어 `IS NOT DISTINCT FROM`과 동등 동작.

### 결과

| 테이블 | 중복 제거 |
|--------|----------:|
| rt_trade | 28,287건 |
| rt_rent | 198,032건 |

### `restore_fk.py` — Remote FK 복구

Remote 측 진단에서 발견: Phase 5 배포 시 `COPY` 후 FK 재설정 누락 → **5개 FK 모두 사라진 상태**.

```python
FKS = [
    ("rt_trade", "rt_trade_apt_id_fkey", "apt_id", "rt_complex", "apt_id"),
    ("rt_rent", "rt_rent_apt_id_fkey", "apt_id", "rt_complex", "apt_id"),
    ("nv_listing", "nv_listing_complex_no_fkey", "complex_no", "nv_complex", "complex_no"),
    ("complex_mapping", "complex_mapping_apt_id_fkey", "apt_id", "rt_complex", "apt_id"),
    ("complex_mapping", "complex_mapping_naver_complex_no_fkey", "naver_complex_no", "nv_complex", "complex_no"),
]

# 각 FK마다: orphan COUNT → DELETE → ALTER TABLE ADD CONSTRAINT
```

고아 레코드 rt_trade 10,028건 / rt_rent 35,246건 삭제 후 FK 5개 복구 완료.

### 교훈

- **O(N²) SQL의 함정**: "작동하는" SQL이 production 규모에서 멈춘다. 인덱스·윈도우 함수 활용으로 복잡도 낮추기.
- **환경 간 상태 드리프트 확인**: Local은 문제없어도 Remote는 배포 과정에서 제약이 사라질 수 있다. 스키마 진단 자동화 필요.

---

## 3. Remote 운영 전환

### 절차

1. **기존 cron 중단**: Dokploy UI에서 `collect_naver daily` / `update_daily.py` 스케줄 비활성화
2. **배포**: `git push origin main` → Dokploy Deploy (8개 커밋 반영)
3. **pg_dump 백업**: 91MB, `/data/aptinsight/data/backups/` 에 보관
4. **migrate 실행** (Remote): 중복 217k 제거 + UNIQUE 추가
5. **restore_fk 실행** (Remote): 고아 45k 삭제 + FK 5개 복구
6. **run_daily 1회 수동 실행**: 2시간 15분 (RT 10분 + NV 2시간 5분)
7. **Dokploy Schedule 등록**: `0 1 * * *` KST, Service=apt-insight, Command=`python -m pipeline.run_daily`

### 검증 리포트

`data/reports/2026-04-17.json`:

```json
{
  "date": "2026-04-17",
  "elapsed_seconds": 8105.4,
  "rt": {"status": "success", "new_complexes": 74, "new_trades": 1145,
         "new_rents": 4023, "deleted_trades": 1008, "deleted_rents": 3636},
  "nv": {"status": "success", "new": 124324, "changed": 3388,
         "kept": 569277, "closed": 339588},
  "status": "success"
}
```

### 최종 Remote DB 상태

| 테이블 | 건수 |
|--------|-----:|
| rt_complex | 15,018 (+74 신규) |
| rt_trade | 624,199 (중복 제거 후) |
| rt_rent | 1,919,687 |
| nv_complex | 22,373 |
| nv_listing (total) | 3,621,955 (active 697k) |
| complex_mapping | 12,271 |

---

## 4. apt-pipeline 서비스 제거

### 배경

Phase 5에서 Dokploy에 두 개 서비스를 만들었다:
- `apt-insight` (Chainlit 8000)
- `apt-pipeline` (sleep infinity, 스케줄러용)

그러나 Schedule은 `docker exec`로 임의 서비스에서 명령을 실행하므로 **별도 컨테이너 불필요**. 게다가 Dokploy가 pipeline 이미지를 자동 재빌드 하지 않아 **구버전 Python 3.12 이미지**가 1달째 남아있었다 — 새 pipeline 코드가 반영되지 않음.

### 조치

1. Dokploy UI → apt-pipeline → Danger Zone → Delete Application
2. 이미지 제거: `docker rmi apttransactioninsight-aptpipeline-qyesha:latest` (909MB)
3. 고아 volume 제거: `docker volume rm apt_transaction_insight_pipeline_data`
4. legacy CSV 경로 정리: `rm -rf /opt/apt-pipeline/` (401MB, `update_daily.py` 시절의 마스터 CSV들)
5. Schedule의 Service를 `apt-insight` 로 변경
6. `docker-compose.yml`: `pipeline` 서비스 블록 제거, `pipeline_data` → `app_data` 리네임

**회수**: 이미지 909MB + legacy CSV 401MB = **약 1.3GB**

### 교훈

- 초기엔 역할 분리(app/pipeline)가 깔끔해 보였지만, **Dokploy의 이미지 자동 재빌드 정책**과 맞지 않아 구버전이 누적됐다. 인프라 도구의 **자동화 경계**를 정확히 파악한 뒤 서비스 분리 여부를 결정해야.

---

## 5. 멀티턴 대화 메모리 (레벨 A)

### 배경

Chainlit 앱에서 "강남구 매매가" 후 "전세가는?" 질문을 던졌을 때, 이전 맥락을 모른 채 "전국 전세"로 답변. LangGraph는 원래 checkpointer로 이 문제를 해결하도록 설계됐는데 초기 구현에 빠져 있었다.

### 3단계 구현 레벨

| 레벨 | 범위 | 저장소 |
|------|------|--------|
| **A. 단일 세션 멀티턴** | 브라우저 세션 동안 기억 | `InMemorySaver` |
| B. 영속 대화 기억 | 재접속해도 복원 | `PostgresSaver` |
| C. 장기 사용자 메모리 | fact 누적 | `PostgresStore` + 추가 노드 |

이번엔 **레벨 A**만 적용 (가장 단순 + 대부분 UX 해결).

### 설계 변천 — 노드 분리 vs 함수 흡수

**1차 시도**: `rewrite_query` 전담 노드 신설.

```
START → rewrite_query → query_generator → ... → synthesize → END
```

사용자 질문 "사이즈 과하지 않나?" 피드백 → **함수로 흡수**:

```python
def query_generator(state):
    user_content = _rewrite_to_standalone(llm, state["messages"])
    # ... 기존 라우팅 로직
```

그래프는 노드 한 개만 늘리지 않고, `query_generator` 내부에서 2단계 LLM 호출.

### 환경 통합

```python
# app.py
@cl.on_chat_start
async def on_chat_start():
    graph = create_supervisor_graph(checkpointer=InMemorySaver())
    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", str(uuid.uuid4()))

@cl.on_message
async def on_message(message):
    graph = cl.user_session.get("graph")
    thread_id = cl.user_session.get("thread_id")
    async for event in graph.astream(
        {"messages": [HumanMessage(content=message.content)]},
        {"configurable": {"thread_id": thread_id}, "recursion_limit": 50},
        stream_mode="updates",
    ):
        ...
```

### Gemini Flash-Lite의 함정

프롬프트 보강만으로 "강남구 매매가 → 전세가는?" 맥락을 잡으려 했으나 **실패**. 여러 지시를 한 프롬프트에 담은 복합 태스크를 Flash-Lite가 일관되게 처리하지 못함.

**해법**: rewrite 전담 프롬프트를 분리. 단순 태스크(대화 → standalone 한 줄)는 Flash-Lite도 잘 수행.

```python
REWRITE_PROMPT = """이전 대화를 반영해 마지막 사용자 질문을
혼자서도 이해 가능한 완전한 한국어 문장 한 줄로 재작성하세요.
지시대명사·생략된 지역/기간/거래유형을 이전 대화의 구체 값으로 채우되,
새 주제(다른 지역명 등)가 명시되면 이전 맥락은 버리세요.
인사나 짧은 잡담은 그대로 반환하세요.
오직 질문 한 줄만 출력. 설명·따옴표·prefix 금지."""
```

### 교훈

- **노드를 늘리는 것이 항상 좋은 설계는 아니다.** State 필드, UI Step, LangGraph 그래프 노출이 모두 늘어난다. 전처리·후처리에 해당하면 함수 호출로 두는 편이 수술적.
- 작은 모델에겐 **태스크를 단순하게 쪼개서** 각 단계마다 한 가지만 시켜라.

---

## 6. 도메인 연결 — apt.deepdata.kr

### DNS + Dokploy Domains

1. Gabia DNS: `apt.deepdata.kr A 187.77.150.150`
2. Dokploy apt-insight → Domains → Add:
   - Host: `apt.deepdata.kr`
   - Port: 8000
   - HTTPS: on, Provider: Let's Encrypt

### 숨겨진 함정 — Hostinger 네트워크 방화벽

설정 후에도 브라우저에서 `ERR_CONNECTION_TIMED_OUT`. 진단:

| 검사 | 결과 |
|------|------|
| `dig apt.deepdata.kr` | 187.77.150.150 ✓ (DNS 정상) |
| HTTP `187.77.150.150/` | 200 OK ✓ (80 포트 열림) |
| HTTPS `187.77.150.150/` | 응답 없음 (443 차단) |
| VPS 내 `ss -tlnp :443` | docker-proxy LISTEN ✓ |
| `Test-NetConnection 443` (클라이언트) | `TcpTestSucceeded: False` |

VPS 내부는 문제없는데 외부에서 443 도달 불가 → **Hostinger hPanel의 네트워크 방화벽**이 443 포트를 차단.

**해결**: Hostinger 방화벽 설정에 `TCP 443 Allow` 규칙 추가 → 즉시 연결.

### 교훈

- VPS 제공자의 **네트워크 레벨 방화벽**과 **OS 레벨 방화벽**(ufw/iptables)은 별개다. 둘 다 확인.
- "DNS OK + 80 OK + 443 timeout" 패턴은 거의 항상 **외부 방화벽** 문제.

---

## 주요 교훈 (교재 독자에게)

1. **교재와 코드의 정합은 교재 품질을 결정한다.** 장별 파일 분리는 독자가 *"지금 읽는 챕터의 코드는 이 파일이구나"* 즉시 찾을 수 있어야 한다.
2. **"작동하는 코드" ≠ "운영 가능한 코드".** 자기조인은 교과서적이지만 prod 규모에선 멈춘다. O(N log N) 기법을 갖춰둬야.
3. **순수함수로 분리할 수 있는 것은 분리하라.** `diff_listings`는 DB/IO 없이 단위 테스트 가능. 교재 설명도 훨씬 쉬워진다.
4. **플랫폼의 자동화 경계를 이해하라.** Dokploy가 어떤 서비스를 자동 재빌드하고 어느 서비스는 그렇지 않은지. 모르면 1개월짜리 구버전 이미지가 쌓인다.
5. **노드 vs 함수**: 외부로 노출할 필요 없는 전·후처리는 함수로 흡수. 노드는 *의미 있는 상태 전이*일 때.
6. **작은 모델의 지시 준수 한계**: Flash-Lite 같은 소형 모델은 복합 지시를 못 따른다. 태스크를 단순 단위로 쪼개서 각각 한 가지만 시켜라.
7. **환경 간 드리프트**: Local과 Remote가 어떻게 다른지 체계적으로 진단하는 스크립트 (제약·FK·테이블 건수·데이터 범위)를 상시 갖춰라.
8. **시행착오 기록의 가치**: "처음엔 자기조인을 썼고 14분 후에도 안 끝나서 CTID로 바꿨다"가 교재 원료다. 최종 답만 보면 왜 그렇게 결정했는지 알 수 없다.

---

## 변경 파일 목록 (이번 Phase)

### 신규

- `pipeline/naver_session.py` — 세션·adaptive delay (10장)
- `pipeline/schemas.py` — 국토부 스키마 변환 (17장 보조)
- `pipeline/build_mapping.py` — rt↔nv 매핑 (14장)
- `pipeline/update_rt_daily.py` — 국토부 일일 + 36개월 cleanup (17장)
- `pipeline/update_nv_daily.py` — 네이버 일일 + diff_listings (18장)
- `pipeline/run_daily.py` — 오케스트레이터 + JSON 리포트 (19장)
- `scripts/migrate_unique_constraints.py` — UNIQUE 제약 1회성 마이그레이션
- `scripts/restore_fk.py` — Remote FK 복구 1회성

### 수정

- `pipeline/collect_naver.py` — 860 → 550줄 (full 모드만)
- `scripts/init_db.py` — UNIQUE 제약 포함한 스키마 DDL
- `agents/graph.py` — `create_supervisor_graph(checkpointer=...)` + `_rewrite_to_standalone`
- `app.py` — InMemorySaver + uuid thread_id + chat_start·on_message
- `docker-compose.yml` — pipeline 서비스 제거, `app_data` 볼륨
- `Dockerfile` — 단일 이미지 (app + pipeline 겸용)
- `CLAUDE.md` — 구조·cron 반영

### 삭제

- `pipeline/update_daily.py` — 기능 분할 완료

### 커밋 체인 (9개)

```
14bed7e refactor(pipeline): extract naver_session and schemas modules
32c2cf7 feat(pipeline): build_mapping module (textbook ch.14)
e67ae09 refactor(collect_naver): remove session/mapping, keep full mode only
e6073db feat(pipeline): update_rt_daily + natural UNIQUE constraints (ch.17)
5fce208 feat(pipeline): update_nv_daily + diff_listings pure function (ch.18)
9e8cf7b feat(pipeline): run_daily orchestrator + JSON report (ch.19); drop update_daily
cbe2f2e feat(scripts): restore_fk for Remote FK repair (one-off)
f87ffe0 docs: update pipeline structure, cron schedule, and devlog
034e4ae chore: remove apt-pipeline service (consolidated into app)
5cf5fca feat(agents): multi-turn conversation memory (level A)
```

---

## 다음 단계 (Phase 7 예고)

Phase 6으로 **구조·인프라**는 정돈됐지만, 실제 질문을 돌려보니 **답변 품질** 문제가 여전하다 — 환각, 위치 질문에 지도 안 뜸, 뉴스가 과거 기사, 수치 표시가 비친화적 등. Phase 7에서 에이전트 답변 품질을 본격적으로 끌어올린다.
