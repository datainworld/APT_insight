"""환경변수 로드 및 프로젝트 설정."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# 프로젝트 루트
BASE_DIR = Path(__file__).resolve().parent.parent

# DB
POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB: str = os.getenv("POSTGRES_DB", "apt_insight")

DATABASE_URL: str = (
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# LLM
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "google")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")

# Embedding
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")

# API Keys
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
DATA_API_KEY: str = os.getenv("DATA_API_KEY", "")
KAKAO_API_KEY: str = os.getenv("KAKAO_API_KEY", "")
NAVER_LAND_COOKIE: str = os.getenv("NAVER_LAND_COOKIE", "")
NAVER_CLIENT_ID: str = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET: str = os.getenv("NAVER_CLIENT_SECRET", "")
