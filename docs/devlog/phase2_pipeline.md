# Phase 2: 데이터 파이프라인 이관

> 날짜: 2026-04-16

## 목표

기존 APT_data_pipeline의 파이프라인(3,514줄)을 간결하게 리팩토링하여 이관한다.

## 리팩토링 결과

| 파일 | 원본 | 신규 | 감소율 |
|------|------|------|--------|
| `pipeline/utils.py` | 149 | 145 | -3% |
| `pipeline/collect_rt.py` | 841 | 236 | **-72%** |
| `pipeline/collect_naver.py` | 1,304 | 506 | **-61%** |
| `pipeline/update_daily.py` | 1,220 | 302 | **-75%** |
| **합계** | **3,514** | **1,189** | **-66%** |

## 주요 변경사항

### 제거한 기능

1. **K-Apt 기본/상세 정보 수집 전체** — devlog #2에 따라 `apt_detail` 테이블 제거
2. **collect_news.py** — devlog #1에 따라 뉴스는 실시간 검색으로 대체
3. **email 알림** — 새 프로젝트에서 미사용
4. **DB 스키마 생성 코드** — `scripts/init_db.py`로 이관
5. **파생 컬럼 계산 로직** — devlog #4에 따라 `deal_diff`, `deal_diff_rate`, `rental_adjusted_deposit` 등 제거

### 중복 제거

- `get_kakao_coords` 3곳 중복 → 1곳으로 통합
- `build_address` 2곳 중복 → 1곳으로 통합
- `_collect_trade_data`/`_collect_rent_data` 동일 패턴 → `_collect_paginated` 추출
- `parse_api_items` 헬퍼 신규 추가 (XML 응답 파싱 중복 제거)
- DB 엔진 중복 정의 제거 → `shared.db` 사용

### 테이블명 변경

소스 prefix 적용 (devlog #3):
- `apt_basic` → `rt_complex`
- `apt_trade` → `rt_trade`
- `apt_rent` → `rt_rent`
- `naver_complex` → `nv_complex`
- `naver_listing` → `nv_listing`

### LAWD_CD 상수화

기존 코드는 API로 아파트 단지 코드를 받아 거기서 LAWD_CD 78개를 추출했다. 단지 코드는 매매/전월세 API 호출에만 쓰였고, apt_detail을 안 쓰므로 Step 1(단지 코드 수집)이 불필요해짐. 수도권 시군구 78개를 `LAWD_CODES` 상수로 정의.

### 네이버 매물 수집 병렬화 (devlog #6)

- `get_cortars()`: 3개 시도(서울/경기/인천)를 병렬 수집
- 매물 수집 워커: 5개 → 8개

## 검증

**2-2: 국토부 1개 구(강남구 11680) × 1개월 테스트 수집**
- 매매 136건, 전월세 1,465건 수집 성공
- 고유 아파트 317건 추출 → 지오코딩 317/317건 성공

**2-3: 네이버 1개 단지(은마아파트 8928) 테스트 수집**
- 매매 매물 47건 수집 성공
- JWT 토큰 획득 및 파싱 정상

## 이슈 및 해결

### 의사결정 사전 누락

Phase 2 작업 중 `docs/devlog/phase0_planning.md`를 읽지 않은 상태로 작업하여 devlog #4(파생 컬럼 제거), #6(네이버 병렬화)를 초기에 반영하지 못함. 지적받은 후 모든 파일에 반영.

이후 운영 규칙으로 추가:
- 메모리에 "코딩 전 devlog 포함 관련 문서 모두 읽기" 저장
- 메모리에 "확인하지 않은 것을 사실처럼 말하지 않기" 저장

## 다음 단계

Phase 3: 에이전트 개발
