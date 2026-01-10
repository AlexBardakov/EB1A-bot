# app/rag/indexer.py
from __future__ import annotations

import re
import os
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from openai import OpenAI  # Требуется: pip install openai

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
    # Имитируем браузер, чтобы USCIS не блокировал запрос
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    r = requests.get(url, timeout=40, headers=headers)
    r.raise_for_status()
    html = r.text

    soup = BeautifulSoup(html, "html.parser")

    # Удаляем лишнее
    for tag in soup(
            ["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    title = (soup.title.get_text(
        strip=True) if soup.title else title_fallback).strip()

    # Извлекаем текст
    text = soup.get_text("\n", strip=True)
    text = _normalize_whitespace(text)

    raw_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    return FetchedPage(
        url=url,
        title=title or title_fallback,
        text=text,
        last_updated=None,
        raw_hash=raw_hash,
    )


def chunk_text(text: str, *, max_chars: int = 2000,
               overlap_chars: int = 200) -> List[str]:
    """
    Разбиваем текст на куски. 2000 символов ~ 400-500 токенов, идеально для RAG.
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
            while len(p) > max_chars:
                chunks.append(p[:max_chars].strip())
                p = p[max_chars - overlap_chars:]
            buf = p
    flush()

    # Добавляем перекрытие (overlap)
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


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Генерируем реальные векторы через OpenAI (text-embedding-3-small).
    Размерность: 1536.
    """
    if not texts:
        return []

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Заменяем переносы строк на пробелы для лучшего качества эмбеддингов
    clean_texts = [t.replace("\n", " ") for t in texts]

    try:
        resp = client.embeddings.create(
            input=clean_texts,
            model="text-embedding-3-small"
        )
        return [d.embedding for d in resp.data]
    except Exception as e:
        print(f"[RAG Error] Embedding failed: {e}")
        raise e


def upsert_page_into_rag(
        session: Session,
        *,
        kind: str,
        page: FetchedPage,
        chunk_prefix: str,
) -> int:
    chunks = chunk_text(page.text)

    if not chunks:
        return 0

    embeddings = embed_texts(chunks)

    upserted = 0
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"{chunk_prefix}-{i:04d}"

        existing = (
            session.query(RagChunk)
            .filter(RagChunk.source_url == page.url,
                    RagChunk.chunk_id == chunk_id)
            .one_or_none()
        )

        meta = {"raw_hash": page.raw_hash, "index": i}
        if existing:
            # Обновляем, если хеш изменился
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