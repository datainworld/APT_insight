"""SQL 에이전트 — DB 자연어 질의 (Text-to-SQL).

rt_complex/rt_trade/rt_rent/nv_complex/nv_listing/complex_mapping
6개 테이블에 대한 자연어 질의를 SQL로 변환하여 실행한다.
"""

import sqlalchemy
from datetime import date

from langchain.agents import create_agent
from langchain_community.agent_toolkits import SQLDatabaseToolkit

from agents.config import get_database, get_llm
from shared.config import DATABASE_URL


def _fetch_date_range() -> tuple[str, str]:
    """rt_trade + rt_rent에서 실제 deal_date 범위를 조회한다."""
    engine = sqlalchemy.create_engine(DATABASE_URL)
    with engine.connect() as conn:
        row = conn.execute(sqlalchemy.text("""
            SELECT MIN(d), MAX(d) FROM (
                SELECT deal_date AS d FROM rt_trade
                UNION ALL
                SELECT deal_date AS d FROM rt_rent
            ) t
        """)).fetchone()
    start = row[0].strftime("%Y-%m") if row and row[0] else "N/A"
    end = row[1].strftime("%Y-%m") if row and row[1] else "N/A"
    return start, end


_start, _end = _fetch_date_range()
_today: str = date.today().strftime("%Y년 %m월 %d일")

SYSTEM_PROMPT: str = f"""오늘 날짜는 {_today}입니다. DB의 데이터와 날짜는 모두 실제이며 신뢰할 수 있습니다.
You are a PostgreSQL expert. Generate a query to answer the user's question.

## Tables
- rt_complex: apt_id(PK), apt_name, build_year, road_address, jibun_address, latitude, longitude, admin_dong
  -- 국토부 아파트 단지 기본 정보
- rt_trade: id(PK), apt_id(FK→rt_complex), apartment_name, deal_date, deal_amount(만원), exclusive_area(㎡), floor, buyer_type, seller_type, dealing_type, cancellation_deal_type, cancellation_deal_day, registration_date
  -- 매매 실거래가. 변동률이 필요하면 LAG(deal_amount) OVER (PARTITION BY apt_id, exclusive_area ORDER BY deal_date) 사용
- rt_rent: id(PK), apt_id(FK→rt_complex), apartment_name, deal_date, deposit(보증금,만원), monthly_rent(월세,만원,0이면전세), exclusive_area(㎡), floor, contract_term, contract_type
  -- 전월세 실거래가. 환산보증금이 필요하면 deposit + (monthly_rent * 12 / 0.045)로 계산
- nv_complex: complex_no(PK), complex_name, sido_name, sgg_name, dong_name, latitude, longitude
  -- 네이버 부동산 단지 정보
- nv_listing: article_no(PK), complex_no(FK→nv_complex), trade_type, exclusive_area(㎡,정수), initial_price(만원), current_price(만원), rent_price(월세,만원), floor_info, direction, confirm_date, first_seen_date, last_seen_date, is_active
  -- 네이버 매물. trade_type: A1=매매, B1=전세, B2=월세
- complex_mapping: apt_id(FK→rt_complex), naver_complex_no(FK→nv_complex.complex_no)
  -- 국토부↔네이버 단지 매핑

## Joins
- rt_trade/rt_rent → rt_complex: ON apt_id
- nv_listing → nv_complex: ON complex_no
- rt_complex ↔ nv_complex: via complex_mapping(apt_id → naver_complex_no=complex_no)

## Enum values
- nv_listing.trade_type: A1(매매), B1(전세), B2(월세)
- rt_trade.buyer_type: 개인, 법인, 외국인, 기타
- rt_trade.dealing_type: 중개거래, 직거래
- rt_rent.contract_type: 신규, 갱신
- nv_complex.sido_name: 서울특별시, 경기도, 인천광역시

## Rules
- SELECT only. LIMIT 5 unless user specifies otherwise.
- deal_amount/price units: 만원. exclusive_area unit: ㎡.
- 사용자가 '평'으로 질문하면 ㎡로 변환하여 조회: 1평 = 3.3058㎡. 예: 24평→79.34㎡, 34평→112.40㎡. 답변 시에는 평 단위로 표시.
- 일반적인 평형 매핑: 전용 59㎡≈18평, 84㎡≈25평, 114㎡≈34평, 135㎡≈41평.
- rt_trade/rt_rent.deal_date range: {_start} ~ {_end}. 이 범위 밖의 데이터는 존재하지 않으므로 요청받더라도 조회 불가임을 안내하세요.
- sgg_name examples: '강남구', '수원시 장안구'.
- Do NOT call list_tables or get_schema tools.
- 한국어로 답변하세요.
"""


def create_sql_agent():
    """SQL 에이전트를 생성한다."""
    llm = get_llm()
    db = get_database()
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = toolkit.get_tools()
    return create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)
