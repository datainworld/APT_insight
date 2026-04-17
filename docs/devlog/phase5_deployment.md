# Phase 5: VPS 배포

> 날짜: 2026-04-16

## 목표

Hostinger VPS(deepdata, 187.77.150.150)의 기존 aptinsight 앱(Dash 기반 APT_insight_03)을 새 Chainlit 앱으로 교체한다.

## 구성

### 저장소

GitHub: `https://github.com/datainworld/APT_insight`

### Dockerfile

- Python 3.13-slim 베이스
- uv로 의존성 설치
- 단일 이미지로 app + 파이프라인 스크립트 실행 겸용 (Schedule의 Command override로 구분)
- EXPOSE 8000, 기본 CMD는 `chainlit run`

### docker-compose.yml (로컬/참고용)

- `db` (pgvector/pgvector:0.8.0-pg18)
- `app` (Chainlit, 8000) — `run_daily` 포함, Dokploy Schedule도 app 서비스에서 실행
- volumes: pgdata, uploads, app_data

_구 `pipeline` 서비스는 2026-04-17 제거됨 (역할 중복). 자세한 내용은 phase6_refactor 참고._

## VPS 배포 절차

### 1. 기존 aptinsight 앱 코드 교체

```bash
ssh deepdata
cd /etc/dokploy/applications/apttransactioninsight-aptinsight-tjld7b/code
git remote set-url origin https://github.com/datainworld/APT_insight.git
git fetch origin
git reset --hard origin/main
```

### 2. DB 준비 (aptdb 컨테이너)

```bash
docker exec <aptdb> psql -U postgres -c 'CREATE DATABASE apt_insight;'
docker exec <aptdb> psql -U postgres -d apt_insight -c 'CREATE EXTENSION IF NOT EXISTS vector;'
# 스키마 수동 생성 (init_db.py 내용을 SQL로 실행)
```

### 3. 기존 데이터 복사 (postgres → apt_insight)

| 테이블 | 건수 |
|--------|------|
| rt_complex | 14,944 |
| rt_trade | 662,208 |
| rt_rent | 2,143,781 |
| nv_complex | 22,366 |
| nv_listing | 3,497,832 |
| complex_mapping | 12,271 |

`COPY TO STDOUT | COPY FROM STDIN` 방식으로 UTF-8 인코딩 파이프.

### 4. Dokploy Environment 탭 설정

```
POSTGRES_HOST=apttransactioninsight-aptdb-vrkyfm
POSTGRES_USER=postgres
POSTGRES_PASSWORD=4444
POSTGRES_PORT=5432
POSTGRES_DB=apt_insight
LLM_PROVIDER=google
LLM_MODEL=gemini-3.1-flash-lite-preview
GOOGLE_API_KEY=...
EMBEDDING_MODEL=gemini-embedding-001
DATA_API_KEY=...
KAKAO_API_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
LANGSMITH_TRACING=false
```

### 5. 볼륨 마운트 (Dokploy)

| Host Path | Mount Path | 용도 |
|-----------|-----------|------|
| `/data/aptinsight/uploads` | `/app/uploads` | PDF 업로드 파일 |
| `/data/aptinsight/data` | `/app/data` | 파이프라인 CSV, 체크포인트 |

### 6. 도메인 설정 (Dokploy Domains 탭)

- Host: `187.77.150.150` (또는 도메인)
- Port: **8000** (기존 8050에서 변경)
- Path: `/`

Traefik이 80 포트로 들어오는 요청을 컨테이너 8000으로 라우팅.

### 7. 이미지 빌드 및 서비스 업데이트

```bash
docker build -t apttransactioninsight-aptinsight-tjld7b:latest .
docker service update --image apttransactioninsight-aptinsight-tjld7b:latest --force apttransactioninsight-aptinsight-tjld7b
```

## 주요 이슈 및 해결

### 1. `.env` 파일 무시됨

**증상:** VPS .env에 변수를 써도 컨테이너가 기본값(`gemini-3.1-flash-lite`)을 사용하여 LLM 호출 실패.

**원인:** Dokploy는 Environment 탭 설정만 컨테이너에 주입. `.env` 파일은 Dokploy 배포 대상이 아님.

**해결:** Dokploy 대시보드의 Environment 탭에서 모든 변수를 직접 설정.

### 2. Dokploy Deploy가 코드를 구 저장소로 리셋

**증상:** Dokploy에서 Deploy 버튼을 누르면 git remote가 원래 URL로 리셋되고 이전 코드(Dash 앱)가 배포됨.

**해결:** Dokploy **General** 탭에서 Git Repository URL을 `https://github.com/datainworld/APT_insight.git`로 변경해야 함. (Phase 5 마무리 시점에 아직 변경 전)

**임시 해결:** 수동으로 `git reset --hard origin/main` 후 `docker build` + `docker service update`.

### 3. 포트 8000 외부 접근 불가

**증상:** `docker service update --publish-add 8000:8000` 후에도 외부에서 `ERR_CONNECTION_TIMED_OUT`.

**원인:** Hostinger VPS의 방화벽이 8000 포트 차단.

**해결:** 80/443은 Traefik이 이미 점유 중이므로 Dokploy Domains 탭에서 포트 8000을 등록하여 Traefik 경유로 접근. **http://187.77.150.150/** (80 포트)로 정상 접속.

## 현재 상태

- 앱 배포 완료: http://187.77.150.150
- 기존 데이터(14k 단지, 662k 매매, 2.1M 전월세, 22k 네이버 단지, 3.5M 매물) 이관 완료
- Chainlit 화면 정상 표시
- 질의 답변 정상 동작

## 남은 작업

1. **Dokploy Git Repository URL 변경** (Deploy 시 새 저장소 사용하도록)
2. **Dokploy Schedules 등록**
   - `0 3 * * *` (03:00 KST): `python -m pipeline.run_daily` (RT → NV 순차, JSON 리포트 저장)
   - (필요 시 수동) `python -m pipeline.build_mapping`: rt_complex ↔ nv_complex 매핑 재실행
3. **NAVER_LAND_COOKIE 설정** (네이버 매물 수집에 필요)
4. **LangSmith 트레이싱 활성화** (선택)
