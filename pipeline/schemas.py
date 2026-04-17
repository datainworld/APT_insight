"""국토부 실거래 원본 API 응답 → DB 스키마 변환 (공통 모듈, 교재 17장 보조).

`collect_rt.py` (초기 36개월 수집)와 `update_rt_daily.py` (일일 슬라이딩 윈도우)가
공용으로 사용한다. 순수 변환 함수 — DB·IO·외부 API 호출 없음.
"""

import pandas as pd


def _parse_money(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def convert_to_trade_schema(raw_data: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """원본 매매 API 응답 → rt_trade 스키마."""
    df = pd.DataFrame(raw_data) if isinstance(raw_data, list) else raw_data.copy()
    if df.empty:
        return pd.DataFrame()

    if "excluUseAr" in df.columns:
        df["excluUseAr"] = pd.to_numeric(df["excluUseAr"], errors="coerce").fillna(0).astype(int)
        df = df[df["excluUseAr"] > 0]

    df["deal_date"] = pd.to_datetime(
        df["dealYear"].astype(str) + "-" +
        df["dealMonth"].astype(str).str.zfill(2) + "-" +
        df["dealDay"].astype(str).str.zfill(2),
        errors="coerce",
    )

    df.rename(columns={
        "aptSeq": "apt_id", "aptNm": "apartment_name", "dealAmount": "deal_amount",
        "excluUseAr": "exclusive_area", "floor": "floor", "buyerGbn": "buyer_type",
        "slerGbn": "seller_type", "dealingGbn": "dealing_type",
        "cdealType": "cancellation_deal_type", "cdealDay": "cancellation_deal_day",
        "rgstDate": "registration_date",
    }, inplace=True)

    df["deal_amount"] = df["deal_amount"].apply(_parse_money)

    cols = ["apt_id", "apartment_name", "deal_date", "deal_amount", "exclusive_area",
            "floor", "buyer_type", "seller_type", "dealing_type",
            "cancellation_deal_type", "cancellation_deal_day", "registration_date"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def convert_to_rent_schema(raw_data: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """원본 전월세 API 응답 → rt_rent 스키마."""
    df = pd.DataFrame(raw_data) if isinstance(raw_data, list) else raw_data.copy()
    if df.empty:
        return pd.DataFrame()

    if "excluUseAr" in df.columns:
        df["excluUseAr"] = pd.to_numeric(df["excluUseAr"], errors="coerce").fillna(0).astype(int)
        df = df[df["excluUseAr"] > 0]

    df["deal_date"] = pd.to_datetime(
        df["dealYear"].astype(str) + "-" +
        df["dealMonth"].astype(str).str.zfill(2) + "-" +
        df["dealDay"].astype(str).str.zfill(2),
        errors="coerce",
    )

    df.rename(columns={
        "aptSeq": "apt_id", "aptNm": "apartment_name", "deposit": "deposit",
        "monthlyRent": "monthly_rent", "excluUseAr": "exclusive_area",
        "floor": "floor", "contractTerm": "contract_term", "contractType": "contract_type",
    }, inplace=True)

    df["deposit"] = df["deposit"].apply(_parse_money)
    df["monthly_rent"] = df["monthly_rent"].apply(_parse_money)

    cols = ["apt_id", "apartment_name", "deal_date", "deposit", "monthly_rent",
            "exclusive_area", "floor", "contract_term", "contract_type"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def extract_complex_info(raw_trades: list[dict], raw_rents: list[dict]) -> pd.DataFrame:
    """매매·전월세 원본 raw를 합쳐 고유 aptSeq만 남긴 DataFrame 반환.

    지오코딩(`get_kakao_coords`)·주소 조합(`build_address`)은 호출자 책임.
    원본 컬럼(aptSeq, aptNm, buildYear, sggNm, umdNm, jibun, roadNm, ...)이 그대로
    보존되므로 호출자가 자유롭게 후처리 가능.
    """
    parts = []
    if raw_trades:
        parts.append(pd.DataFrame(raw_trades))
    if raw_rents:
        parts.append(pd.DataFrame(raw_rents))
    if not parts:
        return pd.DataFrame()

    df = pd.concat(parts, ignore_index=True)
    if df.empty or "aptSeq" not in df.columns:
        return pd.DataFrame()

    df = df.dropna(subset=["aptSeq"])
    df["aptSeq"] = df["aptSeq"].astype(str)
    return df.drop_duplicates(subset=["aptSeq"], keep="first").reset_index(drop=True)
