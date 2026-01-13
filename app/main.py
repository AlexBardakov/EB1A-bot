# app/main.py
import sys
import os
import time
import telebot
from dotenv import load_dotenv

# 1. СНАЧАЛА настраиваем пути и загружаем .env
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

# Загружаем .env ДО импортов из app, чтобы база получила правильный пароль
load_dotenv(os.path.join(root_dir, '.env'))

if root_dir not in sys.path:
    sys.path.append(root_dir)

# 2. ТОЛЬКО ТЕПЕРЬ импортируем модули приложения
from app.storage.db import db_session
from app.telegram.commands import set_active_case, cmd_review_document
from app.telegram.commands_rag import cmd_requirements, cmd_fees, cmd_filing, cmd_premium
from app.core.ingest import save_document_upload

# Инициализация бота
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not found in .env")
    sys.exit(1)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

print("--- EB-1A Bot (Polling Mode) Started ---")


# --- Обработчики команд ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "Привет! Я AI-ассистент по EB-1A.\n\n"
        "**Команды управления:**\n"
        "`/case use <Name>` - Выбрать активный кейс (из cases.json)\n"
        "`/review <DocTitle>` - Проверить документ\n\n"
        "**Справочные команды (RAG):**\n"
        "`/requirements` - Критерии EB-1A\n"
        "`/fees` - Пошлины\n"
        "`/filing` - Адреса подачи\n"
        "`/premium` - Премиум процессинг"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")


@bot.message_handler(commands=['requirements'])
def handle_requirements(message):
    bot.send_chat_action(message.chat.id, 'typing')
    with db_session() as session:
        resp = cmd_requirements(session, str(message.chat.id))
        bot.reply_to(message, resp, parse_mode="Markdown")


@bot.message_handler(commands=['fees'])
def handle_fees(message):
    bot.send_chat_action(message.chat.id, 'typing')
    with db_session() as session:
        resp = cmd_fees(session, str(message.chat.id))
        bot.reply_to(message, resp, parse_mode="Markdown")


@bot.message_handler(commands=['filing'])
def handle_filing(message):
    bot.send_chat_action(message.chat.id, 'typing')
    with db_session() as session:
        resp = cmd_filing(session, str(message.chat.id))
        bot.reply_to(message, resp, parse_mode="Markdown")


@bot.message_handler(commands=['premium'])
def handle_premium(message):
    bot.send_chat_action(message.chat.id, 'typing')
    with db_session() as session:
        resp = cmd_premium(session, str(message.chat.id))
        bot.reply_to(message, resp, parse_mode="Markdown")


@bot.message_handler(commands=['case'])
def handle_case_use(message):
    text = message.text.strip()
    prefix = "/case use "
    if not text.startswith(prefix):
        bot.reply_to(message, "Формат: `/case use <Case Name>`\nПример: `/case use Owner Four Kings`",
                     parse_mode="Markdown")
        return
    case_name = text[len(prefix):].strip()

    with db_session() as session:
        resp = set_active_case(session, str(message.chat.id), case_name)
        bot.reply_to(message, resp)


@bot.message_handler(commands=['review'])
def handle_review(message):
    text = message.text.strip()
    prefix = "/review "
    if not text.startswith(prefix):
        bot.reply_to(message, "Формат: `/review <Doc Title>`", parse_mode="Markdown")
        return
    doc_title = text[len(prefix):].strip()

    bot.reply_to(message, f"🔍 Анализирую документ '{doc_title}'...")
    bot.send_chat_action(message.chat.id, 'typing')

    try:
        with db_session() as session:
            resp = cmd_review_document(session, str(message.chat.id), doc_title)
            # Разбиваем длинные сообщения (Telegram лимит 4096)
            if len(resp) > 4000:
                for x in range(0, len(resp), 4000):
                    bot.send_message(message.chat.id, resp[x:x + 4000], parse_mode="Markdown")
            else:
                bot.reply_to(message, resp, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")


@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        chat_id = str(message.chat.id)
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        file_name = message.document.file_name
        mime_type = message.document.mime_type or "application/octet-stream"

        bot.reply_to(message, "📥 Принял файл. Обрабатываю...")

        with db_session() as session:
            result_text = save_document_upload(
                session,
                chat_id,
                file_name,
                downloaded_file,
                mime_type
            )
            bot.reply_to(message, result_text, parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при загрузке: {e}")

if __name__ == "__main__":
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Bot crashed: {e}")
            time.sleep(5)