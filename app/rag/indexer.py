# app/rag/indexer.py
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Dict, Any

import requests
from bs4 import BeautifulSoup

from sqlalchemy.orm import Session

from app.rag.models import RagChunk


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str
    last_updated: Optional[datetime]
    raw_hash: str


def _normalize_whitespace(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fetch_page(url: str, title_fallback: str = "") -> FetchedPage:
    r = requests.get(url, timeout=40, headers={"User-Agent": "eb1a-bot/1.0"})
    r.raise_for_status()
    html = r.text

    soup = BeautifulSoup(html, "html.parser")

    # Remove obvious nav/script/style
    for tag in soup(["script", "style", "noscript", "header", "footer"]):
        tag.decompose()

    title = (soup.title.get_text(strip=True) if soup.title else title_fallback).strip()

    # Extract text (simple approach; you can improve per-site later)
    text = soup.get_text("\n", strip=True)
    text = _normalize_whitespace(text)

    raw_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    # Optional: try to parse "Last Reviewed/Updated" if present (site-specific; can be enhanced)
    last_updated = None

    return FetchedPage(
        url=url,
        title=title or title_fallback,
        text=text,
        last_updated=last_updated,
        raw_hash=raw_hash,
    )


def chunk_text(text: str, *, max_chars: int = 2500, overlap_chars: int = 250) -> List[str]:
    """
    Simple chunker by paragraphs. Good enough to start.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip()
        else:
            flush()
            # if paragraph itself is too big, split hard
            while len(p) > max_chars:
                chunks.append(p[:max_chars].strip())
                p = p[max_chars - overlap_chars :]
            buf = p

    flush()

    # add overlap between chunks (soft overlap)
    if overlap_chars > 0 and len(chunks) > 1:
        overlapped = []
        prev_tail = ""
        for c in chunks:
            if prev_tail:
                merged = (prev_tail + "\n\n" + c).strip()
                overlapped.append(merged[:max_chars])
            else:
                overlapped.append(c)
            prev_tail = c[-overlap_chars:]
        chunks = overlapped

    return chunks


# ---- Embeddings stub ----
def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Replace with OpenAI embeddings call.
    Must return vectors of the same dimension as RagChunk.embedding (e.g., 1536).
    """
    # Placeholder: DO NOT use in production.
    # Return deterministic pseudo-embeddings so pipeline works.
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        vec = [(b - 128) / 128 for b in h[:1536]]  # not real; just shape-ish
        # Ensure exact length 1536:
        vec = (vec + [0.0] * 1536)[:1536]
        out.append(vec)
    return out


def upsert_page_into_rag(
    session: Session,
    *,
    kind: str,
    page: FetchedPage,
    chunk_prefix: str,
) -> int:
    chunks = chunk_text(page.text)
    embeddings = embed_texts(chunks)

    upserted = 0
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"{chunk_prefix}-{i:04d}"

        existing = (
            session.query(RagChunk)
            .filter(RagChunk.source_url == page.url, RagChunk.chunk_id == chunk_id)
            .one_or_none()
        )

        meta = {"raw_hash": page.raw_hash, "index": i}
        if existing:
            # only update if text changed
            if existing.meta_json.get("raw_hash") != page.raw_hash:
                existing.text = chunk
                existing.embedding = emb
                existing.source_title = page.title
                existing.kind = kind
                existing.meta_json = meta
                existing.source_last_updated = page.last_updated
                upserted += 1
        else:
            rc = RagChunk(
                kind=kind,
                source_url=page.url,
                source_title=page.title,
                chunk_id=chunk_id,
                text=chunk,
                meta_json=meta,
                source_last_updated=page.last_updated,
                embedding=emb,
            )
            session.add(rc)
            upserted += 1

    return upserted
