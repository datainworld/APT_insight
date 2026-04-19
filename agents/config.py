"""에이전트 공유 설정 — LLM, DB, 임베딩, 벡터스토어 팩토리."""

from langchain_core.language_models import BaseChatModel
from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector

from shared.config import (
    DATABASE_URL, LLM_PROVIDER, LLM_MODEL, EMBEDDING_MODEL,
)

# SQL 에이전트가 접근하는 테이블 화이트리스트
INCLUDE_TABLES: list[str] = [
    "rt_complex",
    "rt_trade",
    "rt_rent",
    "nv_complex",
    "nv_listing",
    "complex_mapping",
]


def get_llm(model: str | None = None) -> BaseChatModel:
    """LLM 인스턴스를 반환한다. model 인자 없으면 LLM_MODEL 기본값."""
    model_name = model or LLM_MODEL
    if LLM_PROVIDER == "google":
        return ChatGoogleGenerativeAI(model=model_name)
    elif LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name)
    elif LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name)
    else:
        raise ValueError(f"지원하지 않는 LLM_PROVIDER: {LLM_PROVIDER}")


def get_database() -> SQLDatabase:
    """SQL 에이전트용 SQLDatabase 인스턴스를 반환한다."""
    return SQLDatabase.from_uri(DATABASE_URL, include_tables=INCLUDE_TABLES)


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Google 임베딩 모델 인스턴스를 반환한다."""
    return GoogleGenerativeAIEmbeddings(model=f"models/{EMBEDDING_MODEL}")


def get_vector_store() -> PGVector:
    """RAG 에이전트용 PGVector 벡터스토어를 반환한다."""
    return PGVector(
        embeddings=get_embeddings(),
        collection_name="pdf_docs",
        connection=DATABASE_URL,
    )
