# scripts/update_uscis_sources.py
from __future__ import annotations

from app.storage.db import db_session
from app.rag.sources import RAG_SOURCES
from app.rag.indexer import fetch_page, upsert_page_into_rag


def main():
    total = 0
    with db_session() as session:
        for src in RAG_SOURCES:
            kind = src["kind"]
            url = src["url"]
            title = src.get("title", "")

            page = fetch_page(url, title_fallback=title)
            prefix = kind[:2] + "-" + str(abs(hash(url)) % 10_000_000)

            n = upsert_page_into_rag(session, kind=kind, page=page, chunk_prefix=prefix)
            total += n
            print(f"{kind}: {url} -> upserted {n}")

    print(f"Done. Total upserted: {total}")


if __name__ == "__main__":
    main()
