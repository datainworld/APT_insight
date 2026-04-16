"""RAG 에이전트 — PDF 문서 벡터 검색.

사용자가 업로드한 PDF 문서에서 유사 청크를 검색하여 답변한다.
PGVector의 langchain_pg_embedding 테이블을 사용한다.
"""

from langchain.agents import create_agent
from langchain.tools import tool

from agents.config import get_llm, get_vector_store

SYSTEM_PROMPT: str = """당신은 수도권 아파트 부동산 문서 분석 전문가입니다.
사용자의 질문에 답하기 위해 반드시 search_pdf 도구로 관련 문서를 검색한 후 답변하세요.

규칙:
- 검색된 문서 내용만을 근거로 답변하세요.
- 출처(파일명, 페이지 번호)를 반드시 포함하세요.
- 검색 결과가 없으면 "업로드된 PDF 문서에서 관련 내용을 찾을 수 없습니다"라고 솔직히 안내하세요.
- 한국어로 답변하세요.
"""


def create_rag_agent():
    """RAG 에이전트를 생성한다."""
    llm = get_llm()
    vector_store = get_vector_store()

    @tool(response_format="content_and_artifact")
    def search_pdf(query: str):
        """업로드된 PDF 문서에서 관련 내용을 검색합니다.
        부동산 정책 보고서, 시장 분석 리포트 등에서 검색할 때 사용하세요.
        query: 검색어 (예: '부동산 규제 완화', 'LTV 비율')
        """
        docs = vector_store.similarity_search(query, k=5)
        if not docs:
            return "검색 결과가 없습니다.", []

        serialized = "\n\n".join(
            f"출처: {doc.metadata.get('source', '알 수 없음')} "
            f"(p.{doc.metadata.get('page', '?')})\n"
            f"내용: {doc.page_content}"
            for doc in docs
        )
        return serialized, docs

    return create_agent(llm, [search_pdf], system_prompt=SYSTEM_PROMPT)
