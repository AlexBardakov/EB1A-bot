# scripts/seed_cases.py
import sys
import os
import json
from dotenv import load_dotenv

# Настройка путей
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.append(root_dir)
load_dotenv(os.path.join(root_dir, '.env'))

from app.storage.db import db_session
from app.storage.models import Case

CASES_FILE = os.path.join(root_dir, "cases.json")


def seed_cases():
    print(f"Reading cases from {CASES_FILE}...")

    if not os.path.exists(CASES_FILE):
        print(f"Error: {CASES_FILE} not found. Please create it first.")
        return

    with open(CASES_FILE, "r", encoding="utf-8") as f:
        cases_data = json.load(f)

    with db_session() as session:
        for c_data in cases_data:
            name = c_data.get("name")
            memo = c_data.get("memo", {})

            if not name:
                continue

            existing = session.query(Case).filter(Case.name == name).one_or_none()
            if existing:
                print(f"Updating case '{name}'...")
                existing.memo_json = memo
            else:
                print(f"Creating new case '{name}'...")
                new_case = Case(
                    name=name,
                    memo_json=memo,
                    lock_mode=True
                )
                session.add(new_case)

    print("Done seeding cases.")


if __name__ == "__main__":
    seed_cases()