# Phase 4: Chainlit 웹 UI

> 날짜: 2026-04-16

## 목표

Chainlit 기반 웹 채팅 UI를 구현한다. 에이전트 진행 상황, PDF 업로드, Plotly 차트를 지원한다.

## 구현 내역

### 진행 상황 표시 (Steps)

LangGraph `astream(stream_mode="updates")`로 각 노드의 업데이트를 실시간으로 받아 `cl.Step`으로 표시:

| 노드 | UI 레이블 | 표시 내용 |
|------|----------|----------|
| `query_generator` | > 질의 생성 | [SQL], [News], [RAG] 생성된 질의 |
| `sql_node` | > DB 조회 | 에이전트 결과 요약 (500자) |
| `rag_node` | > PDF 검색 | 에이전트 결과 요약 |
| `news_node` | > 뉴스 검색 | 에이전트 결과 요약 |
| `synthesize` | > 답변 종합 | 최종 답변 |

### PDF 업로드

- 채팅 입력창 왼쪽 클립 아이콘(📎)으로 첨부
- PyMuPDF로 텍스트 추출 → `RecursiveCharacterTextSplitter` (1000자, 200 overlap)
- PGVector `add_documents()` → `langchain_pg_embedding` 테이블 저장
- metadata에 `source`(파일명), `page`(페이지) 저장

**제약:** PDF만, 50MB 이하, 최대 5개. 텍스트 추출 가능한 PDF만 처리.

**설계 시행착오:** 처음에는 `AskFileMessage`로 별도 다이얼로그를 시도했으나 채팅 내부에 인라인 렌더링되는 Chainlit 구조상 "별도 창" 처리 불가. 클립 아이콘 방식으로 정착.

### Plotly 차트

`synthesize`가 `chart_data` 상태를 반환하면 `cl.Plotly(fig)`로 별도 메시지 렌더링.

### Chat Starters

4개 질문 예시 카드로 사용자 관심 유도:

| 카드 | 질문 |
|------|------|
| 급등/급락 아파트 | 최근 3개월간 매매가가 가장 많이 오른/떨어진 아파트는? |
| 갭투자 유망 지역 | 매매가 대비 전세가 비율이 높은 행정동은? |
| 허위매물 의심 지역 | 장기 등록/호가 변동 큰 매물이 많은 지역은? |
| 정책이 시장에 미치는 영향 | 최근 부동산 정책의 매매/전세 영향? |

**설계 결정:**
- 초기에는 "강남 25평 평균가" 같은 기본 질문이었으나 사용자 피드백으로 시장 분석 관점의 흥미로운 주제로 교체
- 이모지 대신 단순 텍스트 사용 (사용자 선호)

### 로고 및 화면

Chainlit 기본 로고를 "APT Insight" 텍스트로 교체.

**시행착오:**
1. SVG logo_file_url 설정 → 크기 제한 때문에 작게 표시됨
2. CSS max-height 해제 시도 → 효과 없음
3. **최종:** `custom.js`로 로고 `<img>` 요소를 HTML 텍스트 블록으로 교체 (32px "APT Insight" + 16px 부제 + 14px 안내)

### 읽어보기 (chainlit.md)

시스템 데이터 설명 중심으로 작성.
- 구체적 건수는 하드코딩 피함 ("최근 36개월", "매일 갱신")
- 3개 에이전트 역할 간략 설명
- PDF 업로드 안내 (제약 조건 포함)
- `<style>` 태그 미지원 → 마크다운만 사용

### Chainlit 설정 (`.chainlit/config.toml`)

- `[UI] name = "APT Insight"`
- `description = "수도권 아파트 거래, 시세, 뉴스를 AI로 분석합니다"`
- `logo_file_url = "/public/logo.svg"`
- `custom_js = "/public/custom.js"` (로고 교체용)
- `spontaneous_file_upload` — PDF만, 50MB, 최대 5개

### 제한 사항

1. **Starters와 on_chat_start 메시지 공존 불가** — `on_chat_start`에서 메시지를 보내면 Starters가 사라짐. 환영 메시지는 로고 SVG/JS로 대체.
2. **iframe/차트 UI 중앙 배치 불가** — Chainlit은 메시지 내부 렌더링만 지원. "읽어보기"에 iframe 불가.
3. **AskFileMessage 별도 창 불가** — 항상 채팅 내부 인라인 표시.

## 검증

- 텍스트 질의 → 3개 에이전트 병렬 호출 + 종합 답변 확인
- PDF 업로드 → 청킹/임베딩/저장 정상
- Plotly 차트 렌더링 정상
- Starters 클릭 → 해당 질문 자동 전송

## 다음 단계

Phase 5: VPS 배포
