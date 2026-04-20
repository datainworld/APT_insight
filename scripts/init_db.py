"""DB 스키마 초기화 — 모든 테이블 생성 + pgvector extension."""

from sqlalchemy import text

from shared.db import get_engine

SQL = """
-- pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 국토부 실거래 (rt_ prefix)
-- ============================================================

CREATE TABLE IF NOT EXISTS rt_complex (
    apt_id          VARCHAR(50) PRIMARY KEY,   -- 국토부 아파트 고유 식별자 (aptSeq)
    apt_name        VARCHAR(100),              -- 아파트 단지명
    build_year      INTEGER,                   -- 건축 연도
    road_address    VARCHAR(200),              -- 도로명 주소
    jibun_address   VARCHAR(200),              -- 지번 주소
    latitude        DOUBLE PRECISION,          -- 위도
    longitude       DOUBLE PRECISION,          -- 경도
    admin_dong      VARCHAR(50),               -- 행정동 (카카오 reverse geocoding)
    sido_name       VARCHAR(20),               -- 시도명 (카카오 reverse geocoding)
    sgg_name        VARCHAR(50)                -- 시군구명 (카카오 reverse geocoding)
);
COMMENT ON TABLE rt_complex IS '국토부 아파트 단지 기본 정보 — 실거래 데이터에서 추출 + 카카오 지오코딩';
CREATE INDEX IF NOT EXISTS idx_rt_complex_address ON rt_complex (road_address);
CREATE INDEX IF NOT EXISTS idx_rt_complex_dong ON rt_complex (admin_dong);
CREATE INDEX IF NOT EXISTS idx_rt_complex_sgg ON rt_complex (sido_name, sgg_name);

CREATE TABLE IF NOT EXISTS rt_trade (
    id                      SERIAL PRIMARY KEY,
    apt_id                  VARCHAR(50) REFERENCES rt_complex(apt_id),  -- 단지 식별자
    apartment_name          VARCHAR(100),              -- 아파트명
    deal_date               DATE,                      -- 거래 일자
    deal_amount             DOUBLE PRECISION,          -- 거래 금액 (단위: 만원)
    exclusive_area          DOUBLE PRECISION,          -- 전용 면적 (단위: ㎡)
    floor                   INTEGER,                   -- 층
    buyer_type              VARCHAR(50),               -- 매수자 유형 (개인/법인/외국인 등)
    seller_type             VARCHAR(50),               -- 매도자 유형
    dealing_type            VARCHAR(50),               -- 거래 유형 (중개거래/직거래)
    cancellation_deal_type  VARCHAR(50),               -- 해제 사유 유형
    cancellation_deal_day   VARCHAR(20),               -- 해제 등록일
    registration_date       VARCHAR(20)                -- 신고일
);
COMMENT ON TABLE rt_trade IS '아파트 매매 실거래가 (국토부 API, 36개월 rolling) — 변동률은 SQL 윈도우 함수로 계산';
ALTER TABLE rt_trade DROP CONSTRAINT IF EXISTS rt_trade_natural_uq;
ALTER TABLE rt_trade ADD CONSTRAINT rt_trade_natural_uq
    UNIQUE (apt_id, deal_date, deal_amount, exclusive_area, floor);
CREATE INDEX IF NOT EXISTS idx_rt_trade_apt_date ON rt_trade (apt_id, deal_date);
CREATE INDEX IF NOT EXISTS idx_rt_trade_date ON rt_trade (deal_date);
CREATE INDEX IF NOT EXISTS idx_rt_trade_area_amount ON rt_trade (exclusive_area, deal_amount);

CREATE TABLE IF NOT EXISTS rt_rent (
    id              SERIAL PRIMARY KEY,
    apt_id          VARCHAR(50) REFERENCES rt_complex(apt_id),  -- 단지 식별자
    apartment_name  VARCHAR(100),              -- 아파트명
    deal_date       DATE,                      -- 거래 일자
    deposit         DOUBLE PRECISION,          -- 보증금 (단위: 만원)
    monthly_rent    DOUBLE PRECISION,          -- 월세 (단위: 만원, 0이면 전세)
    exclusive_area  DOUBLE PRECISION,          -- 전용 면적 (단위: ㎡)
    floor           INTEGER,                   -- 층
    contract_term   VARCHAR(50),               -- 계약 기간
    contract_type   VARCHAR(50)                -- 계약 유형 (신규/갱신)
);
COMMENT ON TABLE rt_rent IS '아파트 전월세 실거래가 (국토부 API, 36개월 rolling) — monthly_rent=0이면 전세, 환산보증금은 SQL로 계산';
ALTER TABLE rt_rent DROP CONSTRAINT IF EXISTS rt_rent_natural_uq;
ALTER TABLE rt_rent ADD CONSTRAINT rt_rent_natural_uq
    UNIQUE (apt_id, deal_date, deposit, monthly_rent, exclusive_area, floor);
CREATE INDEX IF NOT EXISTS idx_rt_rent_apt_date ON rt_rent (apt_id, deal_date);
CREATE INDEX IF NOT EXISTS idx_rt_rent_deposit ON rt_rent (deposit);

-- ============================================================
-- 네이버 매물 (nv_ prefix)
-- ============================================================

CREATE TABLE IF NOT EXISTS nv_complex (
    complex_no      VARCHAR(20) PRIMARY KEY,   -- 네이버 단지 고유번호
    complex_name    VARCHAR(100),              -- 단지명
    sido_name       VARCHAR(20),               -- 시도명 (서울특별시/경기도/인천광역시)
    sgg_name        VARCHAR(50),               -- 시군구명
    dong_name       VARCHAR(50),               -- 행정동명 (카카오 API 변환)
    latitude        DOUBLE PRECISION,          -- 위도
    longitude       DOUBLE PRECISION           -- 경도
);
COMMENT ON TABLE nv_complex IS '네이버 부동산 아파트 단지 정보 — 증분 수집';
CREATE INDEX IF NOT EXISTS idx_nv_complex_sgg ON nv_complex (sgg_name, dong_name);

CREATE TABLE IF NOT EXISTS nv_listing (
    article_no      VARCHAR(20) PRIMARY KEY,   -- 네이버 매물 고유번호
    complex_no      VARCHAR(20) REFERENCES nv_complex(complex_no),  -- 단지번호 (FK)
    trade_type      VARCHAR(10),               -- 거래유형: A1=매매, B1=전세, B2=월세
    exclusive_area  INTEGER,                   -- 전용 면적 (단위: ㎡, 정수)
    initial_price   INTEGER,                   -- 최초 등록 호가 (단위: 만원)
    current_price   INTEGER,                   -- 현재 호가 (단위: 만원)
    rent_price      INTEGER,                   -- 월세 (단위: 만원, B2인 경우만)
    floor_info      VARCHAR(10),               -- 층 정보
    direction       VARCHAR(10),               -- 향
    confirm_date    DATE,                      -- 매물 확인 일자
    first_seen_date DATE,                      -- 최초 수집 일자
    last_seen_date  DATE,                      -- 마지막 확인 일자
    is_active       BOOLEAN DEFAULT TRUE       -- 현재 활성 여부
);
COMMENT ON TABLE nv_listing IS '네이버 부동산 매물 — 증분 수집, is_active=false이면 종료된 매물';
CREATE INDEX IF NOT EXISTS idx_nv_listing_complex ON nv_listing (complex_no);
CREATE INDEX IF NOT EXISTS idx_nv_listing_trade ON nv_listing (trade_type);
CREATE INDEX IF NOT EXISTS idx_nv_listing_active ON nv_listing (is_active, last_seen_date);

-- ============================================================
-- 단지 매핑
-- ============================================================

CREATE TABLE IF NOT EXISTS complex_mapping (
    apt_id              VARCHAR(50) PRIMARY KEY REFERENCES rt_complex(apt_id),
    naver_complex_no    VARCHAR(20) REFERENCES nv_complex(complex_no),
    mapping_method      VARCHAR(20),               -- DISTANCE 또는 NAME_SIMILARITY
    confidence_score    DOUBLE PRECISION,           -- 매핑 신뢰도 점수
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE complex_mapping IS '국토부 apt_id ↔ 네이버 complex_no 매핑 — 공간+텍스트 유사도 기반';

-- NOTE: PDF 벡터 저장은 LangChain PGVector가 자체 테이블(langchain_pg_embedding)을 관리한다.
-- 별도 pdf_document/pdf_chunk 테이블을 생성하지 않는다.

-- ============================================================
-- 뉴스 기사 (news_articles) — Phase C 대시보드 /insight + 홈 뉴스 패널용
-- ============================================================

CREATE TABLE IF NOT EXISTS news_articles (
    id              BIGSERIAL PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,             -- Naver originallink
    title           TEXT NOT NULL,
    description     TEXT,                             -- Naver description (HTML-stripped)
    body            TEXT,                             -- 본문 스크랩 (실패 시 NULL)
    publisher       VARCHAR(100),                     -- 언론사명 (og:site_name)
    published_at    TIMESTAMPTZ,                      -- KST 기준 publish datetime
    scope           VARCHAR(20),                      -- regional | national | policy | unknown
    sido_name       VARCHAR(20),                      -- scope=regional 일 때 채움
    sgg_name        VARCHAR(50),                      -- scope=regional 일 때 채움
    category        VARCHAR(30),                      -- market | policy | rates | other
    ad_filtered     BOOLEAN DEFAULT FALSE,            -- 광고성 분류 (리스트에서 제외용)
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE news_articles IS '네이버 검색 API 수집 부동산 뉴스 — 일일 갱신, URL 유니크';
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_scope ON news_articles (scope, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_sgg ON news_articles (sgg_name, published_at DESC) WHERE sgg_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_news_category ON news_articles (category, published_at DESC);

-- ============================================================
-- Materialized Views (mv_metrics_*) — 시군구/단지 집계, Phase C 대시보드 가속용
-- run_daily.py 에서 REFRESH MATERIALIZED VIEW CONCURRENTLY 수행
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_metrics_by_sgg AS
WITH trade AS (
    SELECT c.sido_name, c.sgg_name,
           t.deal_date, t.deal_amount, t.exclusive_area
    FROM rt_trade t JOIN rt_complex c ON t.apt_id = c.apt_id
    WHERE c.sido_name IS NOT NULL AND c.sgg_name IS NOT NULL
),
rent AS (
    SELECT c.sido_name, c.sgg_name,
           r.deal_date, r.deposit
    FROM rt_rent r JOIN rt_complex c ON r.apt_id = c.apt_id
    WHERE c.sido_name IS NOT NULL AND c.sgg_name IS NOT NULL
      AND r.monthly_rent = 0
)
SELECT
    sido_name AS sido,
    sgg_name  AS sgg,
    COUNT(*) FILTER (WHERE deal_date >= CURRENT_DATE - INTERVAL '6 months')  AS trade_count_6m,
    COUNT(*) FILTER (WHERE deal_date >= CURRENT_DATE - INTERVAL '12 months') AS trade_count_12m,
    COUNT(*)                                                                 AS trade_count_36m,
    AVG(deal_amount) FILTER (WHERE deal_date >= CURRENT_DATE - INTERVAL '6 months')  AS avg_price_6m,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deal_amount / NULLIF(exclusive_area, 0))
      FILTER (WHERE deal_date >= CURRENT_DATE - INTERVAL '6 months' AND exclusive_area > 0) AS median_ppm2_6m,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deal_amount / NULLIF(exclusive_area, 0))
      FILTER (WHERE exclusive_area > 0)                                                    AS median_ppm2_36m,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deal_amount)
      FILTER (WHERE deal_date >= CURRENT_DATE - INTERVAL '6 months')                       AS sale_median_6m,
    (
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r2.deposit)
        FROM rent r2
        WHERE r2.sido_name = trade.sido_name AND r2.sgg_name = trade.sgg_name
          AND r2.deal_date >= CURRENT_DATE - INTERVAL '6 months'
    )                                                                                      AS jeonse_median_6m
FROM trade
GROUP BY sido_name, sgg_name;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_metrics_by_sgg ON mv_metrics_by_sgg (sido, sgg);
COMMENT ON MATERIALIZED VIEW mv_metrics_by_sgg IS
    '시군구별 집계 — 거래건수(6M/12M/36M), 평균매매, 평당가 중위(6M/36M), 전세 중위(6M). run_daily에서 REFRESH';

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_metrics_by_complex AS
SELECT
    c.apt_id, c.apt_name, c.sido_name AS sido, c.sgg_name AS sgg, c.admin_dong,
    c.build_year, c.latitude, c.longitude,
    COUNT(*) FILTER (WHERE t.deal_date >= CURRENT_DATE - INTERVAL '3 months')  AS trade_count_3m,
    COUNT(*) FILTER (WHERE t.deal_date >= CURRENT_DATE - INTERVAL '6 months')  AS trade_count_6m,
    COUNT(*) FILTER (WHERE t.deal_date >= CURRENT_DATE - INTERVAL '12 months') AS trade_count_12m,
    COUNT(*)                                                                   AS trade_count_36m,
    AVG(t.deal_amount) FILTER (WHERE t.deal_date >= CURRENT_DATE - INTERVAL '6 months') AS avg_price_6m,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.deal_amount / NULLIF(t.exclusive_area, 0))
      FILTER (WHERE t.deal_date >= CURRENT_DATE - INTERVAL '6 months' AND t.exclusive_area > 0) AS median_ppm2_6m,
    MAX(t.deal_date)                                                                  AS last_deal_date
FROM rt_trade t
JOIN rt_complex c ON t.apt_id = c.apt_id
WHERE c.sido_name IS NOT NULL AND c.sgg_name IS NOT NULL
GROUP BY c.apt_id, c.apt_name, c.sido_name, c.sgg_name, c.admin_dong,
         c.build_year, c.latitude, c.longitude;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_metrics_by_complex ON mv_metrics_by_complex (apt_id);
CREATE INDEX IF NOT EXISTS idx_mv_metrics_complex_sgg ON mv_metrics_by_complex (sido, sgg);
COMMENT ON MATERIALIZED VIEW mv_metrics_by_complex IS
    '단지별 집계 — 거래건수 윈도우별, 평균매매/평당가 중위(6M), 최근 거래일. run_daily에서 REFRESH';

-- ============================================================
-- 컬럼 COMMENT (Text-to-SQL 최적화)
-- ============================================================

-- rt_complex
COMMENT ON COLUMN rt_complex.apt_id IS '국토부 아파트 고유 식별자 (aptSeq)';
COMMENT ON COLUMN rt_complex.apt_name IS '아파트 단지명';
COMMENT ON COLUMN rt_complex.build_year IS '건축 연도';
COMMENT ON COLUMN rt_complex.road_address IS '도로명 주소';
COMMENT ON COLUMN rt_complex.jibun_address IS '지번 주소';
COMMENT ON COLUMN rt_complex.latitude IS '위도';
COMMENT ON COLUMN rt_complex.longitude IS '경도';
COMMENT ON COLUMN rt_complex.admin_dong IS '행정동 (카카오 API 변환)';
COMMENT ON COLUMN rt_complex.sido_name IS '시도명 (서울특별시/경기도/인천광역시)';
COMMENT ON COLUMN rt_complex.sgg_name IS '시군구명';

-- rt_trade
COMMENT ON COLUMN rt_trade.apt_id IS '단지 식별자 (rt_complex.apt_id FK)';
COMMENT ON COLUMN rt_trade.apartment_name IS '아파트명';
COMMENT ON COLUMN rt_trade.deal_date IS '거래 일자';
COMMENT ON COLUMN rt_trade.deal_amount IS '거래 금액 (단위: 만원)';
COMMENT ON COLUMN rt_trade.exclusive_area IS '전용 면적 (단위: ㎡)';
COMMENT ON COLUMN rt_trade.floor IS '층';
COMMENT ON COLUMN rt_trade.buyer_type IS '매수자 유형 (개인/법인/외국인 등)';
COMMENT ON COLUMN rt_trade.seller_type IS '매도자 유형';
COMMENT ON COLUMN rt_trade.dealing_type IS '거래 유형 (중개거래/직거래)';
COMMENT ON COLUMN rt_trade.cancellation_deal_type IS '해제 사유 유형';
COMMENT ON COLUMN rt_trade.cancellation_deal_day IS '해제 등록일';
COMMENT ON COLUMN rt_trade.registration_date IS '신고일';

-- rt_rent
COMMENT ON COLUMN rt_rent.apt_id IS '단지 식별자 (rt_complex.apt_id FK)';
COMMENT ON COLUMN rt_rent.apartment_name IS '아파트명';
COMMENT ON COLUMN rt_rent.deal_date IS '거래 일자';
COMMENT ON COLUMN rt_rent.deposit IS '보증금 (단위: 만원)';
COMMENT ON COLUMN rt_rent.monthly_rent IS '월세 (단위: 만원, 0이면 전세)';
COMMENT ON COLUMN rt_rent.exclusive_area IS '전용 면적 (단위: ㎡)';
COMMENT ON COLUMN rt_rent.floor IS '층';
COMMENT ON COLUMN rt_rent.contract_term IS '계약 기간';
COMMENT ON COLUMN rt_rent.contract_type IS '계약 유형 (신규/갱신)';

-- nv_complex
COMMENT ON COLUMN nv_complex.complex_no IS '네이버 단지 고유번호';
COMMENT ON COLUMN nv_complex.complex_name IS '단지명';
COMMENT ON COLUMN nv_complex.sido_name IS '시도명 (서울특별시/경기도/인천광역시)';
COMMENT ON COLUMN nv_complex.sgg_name IS '시군구명';
COMMENT ON COLUMN nv_complex.dong_name IS '행정동명 (카카오 API 변환)';
COMMENT ON COLUMN nv_complex.latitude IS '위도';
COMMENT ON COLUMN nv_complex.longitude IS '경도';

-- nv_listing
COMMENT ON COLUMN nv_listing.article_no IS '네이버 매물 고유번호';
COMMENT ON COLUMN nv_listing.complex_no IS '단지번호 (nv_complex.complex_no FK)';
COMMENT ON COLUMN nv_listing.trade_type IS '거래유형: A1=매매, B1=전세, B2=월세';
COMMENT ON COLUMN nv_listing.exclusive_area IS '전용 면적 (단위: ㎡, 정수)';
COMMENT ON COLUMN nv_listing.initial_price IS '최초 등록 호가 (단위: 만원)';
COMMENT ON COLUMN nv_listing.current_price IS '현재 호가 (단위: 만원)';
COMMENT ON COLUMN nv_listing.rent_price IS '월세 (단위: 만원, B2인 경우만)';
COMMENT ON COLUMN nv_listing.floor_info IS '층 정보';
COMMENT ON COLUMN nv_listing.direction IS '향';
COMMENT ON COLUMN nv_listing.confirm_date IS '매물 확인 일자';
COMMENT ON COLUMN nv_listing.first_seen_date IS '최초 수집 일자';
COMMENT ON COLUMN nv_listing.last_seen_date IS '마지막 확인 일자';
COMMENT ON COLUMN nv_listing.is_active IS '현재 활성 여부 (true=노출중, false=종료)';

-- complex_mapping
COMMENT ON COLUMN complex_mapping.apt_id IS '국토부 단지 식별자 (rt_complex FK)';
COMMENT ON COLUMN complex_mapping.naver_complex_no IS '네이버 단지번호 (nv_complex FK)';
COMMENT ON COLUMN complex_mapping.mapping_method IS '매핑 방법: DISTANCE 또는 NAME_SIMILARITY';
COMMENT ON COLUMN complex_mapping.confidence_score IS '매핑 신뢰도 점수';
COMMENT ON COLUMN complex_mapping.created_at IS '매핑 생성 시각';
"""


def main() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text(SQL))
        conn.commit()
    print("스키마 초기화 완료.")


if __name__ == "__main__":
    main()
