"""PDF 문서 → 페이지별 텍스트 → 청킹 → PGVector 적재.

agents/ 수정 금지 (스펙 0.2) 정책 때문에 rag_agent 내부에 적재 로직을 둘 수 없어
pipeline 쪽에 배치한다. agents.config.get_vector_store() 만 재사용한다.

사용:
    from pipeline.ingest_pdf import ingest_pdf
    result = ingest_pdf("uploads/report.pdf")
    # result.pages, result.chunks
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from langchain_core.documents import Document

from agents.config import get_vector_store

_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 150
_BREAKPOINTS = ("\n\n", "\n", ". ", "。", "! ", "? ", " ")


@dataclass
class IngestResult:
    source: str
    pages: int
    chunks: int
    uploaded_at: str  # ISO 8601 UTC


def _split_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """문단/문장 경계 우선 청킹. langchain 의존 없이 가볍게 구현.

    Strategy: chunk_size 문자 이내에서 가장 뒤쪽 경계를 찾아 자르고, overlap 만큼 앞쪽을 겹친다.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            best = -1
            for sep in _BREAKPOINTS:
                idx = text.rfind(sep, start, end)
                if idx > best:
                    best = idx + len(sep)
            if best > start:
                end = best
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _extract_pages(pdf_path: Path) -> list[str]:
    doc = fitz.open(str(pdf_path))
    try:
        return [doc[i].get_text() or "" for i in range(doc.page_count)]
    finally:
        doc.close()


def ingest_pdf(path: str | Path, source_name: str | None = None) -> IngestResult:
    """PDF 경로를 받아 청킹·임베딩·적재. 결과 메타정보 반환.

    Args:
        path: 로컬 파일 경로
        source_name: 벡터 메타데이터에 저장할 표시 이름 (기본: 파일명)

    Returns:
        IngestResult(source, pages, chunks, uploaded_at)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    source = source_name or p.name
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    page_texts = _extract_pages(p)
    docs: list[Document] = []
    for page_idx, page_text in enumerate(page_texts):
        for chunk in _split_text(page_text):
            docs.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "source": source,
                        "page": page_idx + 1,
                        "uploaded_at": now_iso,
                    },
                )
            )

    if docs:
        vector_store = get_vector_store()
        vector_store.add_documents(docs)

    return IngestResult(
        source=source,
        pages=len(page_texts),
        chunks=len(docs),
        uploaded_at=now_iso,
    )
