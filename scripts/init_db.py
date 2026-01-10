# scripts/init_db.py
import sys
import os
from dotenv import load_dotenv

# Настройка путей
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
env_path = os.path.join(root_dir, '.env')

print(f"Loading env from: {env_path}")
load_dotenv(env_path)
sys.path.append(root_dir)

from sqlalchemy import text
from app.storage.db import engine, DATABASE_URL
from app.storage.models import Base

# --- ВАЖНО: Импортируем RAG модели, чтобы они зарегистрировались в Base.metadata ---
import app.rag.models


def init_db():
    print("Initializing database...")

    # 1. Включаем расширение pgvector
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("Extension 'vector' enabled.")
        except Exception as e:
            print(f"Warning: Could not enable 'vector' extension. Ensure PGVector is installed in Docker. Error: {e}")

    # 2. Создаем все таблицы (включая rag_chunks)
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")


if __name__ == "__main__":
    init_db()