# app/rag/retriever.py
from __future__ import annotations

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from pgvector.sqlalchemy import Vector

from app.rag.models import RagChunk
from app.rag.indexer import embed_texts


def retrieve_snippets(
    session: Session,
    *,
    query: str,
    kind_filter: Optional[List[str]] = None,
    top_k: int = 8,
) -> str:
    q_emb = embed_texts([query])[0]

    stmt = select(RagChunk)
    if kind_filter:
        stmt = stmt.where(RagChunk.kind.in_(kind_filter))

    # pgvector cosine distance: use `.cosine_distance`
    # order by smallest distance
    stmt = stmt.order_by(RagChunk.embedding.cosine_distance(q_emb)).limit(top_k)

    rows = session.execute(stmt).scalars().all()

    if not rows:
        return ""

    # Render with compact citations
    rendered = []
    for r in rows:
        rendered.append(
            f"[{r.kind}] {r.source_title}\nURL: {r.source_url}\nCHUNK: {r.chunk_id}\n---\n{r.text}\n"
        )
    return "\n\n".join(rendered).strip()
