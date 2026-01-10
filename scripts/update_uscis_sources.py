# scripts/update_uscis_sources.py
from __future__ import annotations

import sys
import os
from dotenv import load_dotenv

# Настройка путей
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
env_path = os.path.join(root_dir, '.env')
load_dotenv(env_path)
sys.path.append(root_dir)

from app.storage.db import db_session
from app.rag.sources import RAG_SOURCES
from app.rag.indexer import fetch_page, upsert_page_into_rag


def main():
    print("Starting USCIS sources update...")
    total = 0

    with db_session() as session:
        for src in RAG_SOURCES:
            kind = src["kind"]
            url = src["url"]
            title = src.get("title", "")

            print(f"Processing [{kind}] {url}...")

            try:
                # Скачиваем страницу
                page = fetch_page(url, title_fallback=title)

                # Генерируем префикс
                prefix = kind[:3] + "-" + str(abs(hash(url)) % 10_000_000)

                # Сохраняем в векторную базу
                n = upsert_page_into_rag(session, kind=kind, page=page, chunk_prefix=prefix)

                # Фиксируем успех (commit делается автоматически контекстным менеджером в конце,
                # но можно делать flush, чтобы видеть прогресс)
                session.flush()

                total += n
                print(f" -> Upserted {n} chunks.")

            except Exception as e:
                # ВАЖНО: Если произошла ошибка, откатываем текущую транзакцию,
                # чтобы сессия осталась живой для следующих итераций
                session.rollback()
                print(f" -> ERROR fetching/processing {url}: {e}")

    print(f"\nDone. Total chunks upserted/updated: {total}")


if __name__ == "__main__":
    main()