# app/main.py
from dotenv import load_dotenv
load_dotenv()  # Загрузит .env из корня проекта

from __future__ import annotations

import os
import requests
from fastapi import FastAPI, Request
from app.storage.db import db_session
from app.telegram.commands import set_active_case, cmd_review_document
from app.telegram.commands_rag import cmd_requirements, cmd_fees, cmd_filing, \
    cmd_premium

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def send_telegram_message(chat_id: str, text: str):
    if not TELEGRAM_BOT_TOKEN:
        print("[WARN] TELEGRAM_BOT_TOKEN not set, cannot send message.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"  # Или "HTML", если хотите форматирование
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")


@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    payload = await req.json()

    # Простейший парсинг
    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

    reply_text = "Я не знаю такой команды. Попробуйте /requirements или /case use."

    try:
        with db_session() as session:
            # --- Роутинг команд ---
            if text.startswith("/case use "):
                case_name = text.replace("/case use ", "", 1).strip()
                reply_text = set_active_case(session, chat_id, case_name)

            elif text.startswith("/review "):
                doc_title = text.replace("/review ", "", 1).strip()
                # Это долгая операция, в продакшене лучше делать через BackgroundTasks
                reply_text = cmd_review_document(session, chat_id, doc_title)

            elif text == "/requirements":
                reply_text = cmd_requirements(session, chat_id)
            elif text == "/fees":
                reply_text = cmd_fees(session, chat_id)
            elif text == "/filing":
                reply_text = cmd_filing(session, chat_id)
            elif text == "/premium":
                reply_text = cmd_premium(session, chat_id)

            # Если команда не распознана, логика "эхо" или помощь
            else:
                pass

                # Отправляем ответ
        send_telegram_message(chat_id, reply_text)

    except Exception as e:
        error_msg = f"Произошла ошибка: {str(e)}"
        print(error_msg)
        send_telegram_message(chat_id, error_msg)

    return {"ok": True}