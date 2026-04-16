"""SQLAlchemy 엔진 팩토리."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from shared.config import DATABASE_URL


def get_engine() -> Engine:
    """DATABASE_URL로 SQLAlchemy 엔진을 생성한다."""
    return create_engine(DATABASE_URL)


def check_connection() -> bool:
    """DB 연결을 테스트한다. 성공 시 True, 실패 시 False."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"DB 연결 실패: {e}")
        return False
