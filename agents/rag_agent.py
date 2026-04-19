"""RAG 에이전트 — PDF 문서 벡터 검색.

사용자가 업로드한 PDF 문서에서 유사 청크를 검색하여 답변한다.
PGVector의 langchain_pg_embedding 테이블을 사용한다.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from agents.config import get_llm, get_vector_store

SYSTEM_PROMPT: str = """당신은 수도권 아파트 부동산 문서 분석 전문가입니다.
제공된 검색 결과만을 근거로 사용자의 질문에 답변하세요.

규칙:
- 검색된 문서 내용만을 근거로 답변하세요.
- 출처(파일명, 페이지 번호)를 반드시 포함하세요.
- 검색 결과가 없으면 "업로드된 PDF 문서에서 관련 내용을 찾을 수 없습니다"라고 솔직히 안내하세요.
- 한국어로 답변하세요.
"""


def _extract_text(content) -> str:
    """Gemini가 content를 리스트로 반환할 때 텍스트를 추출한다."""
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    return content if isinstance(content, str) else str(content)


def _search_chunks(query: str, k: int = 5) -> str:
    """PGVector 유사도 검색 → 포매팅 문자열. 결과 없으면 빈 문자열."""
    vector_store = get_vector_store()
    docs = vector_store.similarity_search(query, k=k)
    if not docs:
        return ""
    return "\n\n".join(
        f"출처: {doc.metadata.get('source', '알 수 없음')} "
        f"(p.{doc.metadata.get('page', '?')})\n"
        f"내용: {doc.page_content}"
        for doc in docs
    )


def run_rag(query: str) -> str:
    """질의 → PDF 벡터 검색 → LLM 1회 호출로 요약."""
    chunks = _search_chunks(query)
    if not chunks:
        return "업로드된 PDF 문서에서 관련 내용을 찾을 수 없습니다."

    llm = get_llm()
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"[사용자 질의]\n{query}\n\n[검색된 문서 청크]\n{chunks}"),
    ])
    return _extract_text(response.content)
