# scripts/init_db.py
import sys
import os
from dotenv import load_dotenv

# 1. Явно загружаем переменные из .env файла
# Ищем .env в родительской папке (корне проекта)
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
env_path = os.path.join(root_dir, '.env')

print(f"Loading env from: {env_path}")
load_dotenv(env_path)

# Добавляем корневую папку в sys.path
sys.path.append(root_dir)

from sqlalchemy import text
from app.storage.db import engine, DATABASE_URL
from app.storage.models import Base


def init_db():
    # Для отладки выведем часть URL (скрыв пароль), чтобы убедиться, что он подтянулся
    print(
        f"Connecting to DB using URL from env: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'INVALID URL'}")

    print("Initializing database...")

    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("Extension 'vector' enabled.")
        except Exception as e:
            print(f"Warning: Could not enable 'vector' extension. Error: {e}")

    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")


if __name__ == "__main__":
    init_db()