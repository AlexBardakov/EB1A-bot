# app/main.py
from __future__ import annotations

from fastapi import FastAPI, Request
from app.storage.db import db_session
from app.telegram.commands import set_active_case, cmd_review_document
from app.telegram.commands_rag import cmd_requirements, cmd_fees, cmd_filing, cmd_premium

app = FastAPI()


@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    payload = await req.json()

    # Minimal Telegram parsing (you will expand this):
    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

    reply_text = "Unknown command."

    with db_session() as session:
        if text.startswith("/case use "):
            case_name = text.replace("/case use ", "", 1).strip()
            reply_text = set_active_case(session, chat_id, case_name)

        elif text.startswith("/review "):
            doc_title = text.replace("/review ", "", 1).strip()
            reply_text = cmd_review_document(session, chat_id, doc_title)

        elif text == "/requirements":
            reply_text = cmd_requirements(session, chat_id)
        elif text == "/fees":
            reply_text = cmd_fees(session, chat_id)
        elif text == "/filing":
            reply_text = cmd_filing(session, chat_id)
        elif text == "/premium":
            reply_text = cmd_premium(session, chat_id)

    # Send reply via Telegram API (left as an exercise; keep token in env)
    # requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={...})

    return {"ok": True, "reply": reply_text}
