# app/main.py
import sys
import os
import time
import telebot
from telebot import types
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
load_dotenv(os.path.join(root_dir, '.env'))

if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.storage.db import db_session
from app.telegram.commands import (
    set_active_case,
    cmd_review_document,
    cmd_list_documents,
    cmd_delete_document,
    cmd_add_manual_evidence,
    cmd_list_cases,
    get_all_cases,
    get_evidence_tags,  # <-- NEW
    get_evidence_by_tag  # <-- NEW
)
from app.telegram.commands_rag import cmd_requirements, cmd_fees, cmd_filing, cmd_premium
from app.core.ingest import save_document_upload

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not found in .env")
    sys.exit(1)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

print("--- EB-1A Bot (Polling Mode) Started ---")


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    help_text = (
        "🤖 **EB-1A Assistant Bot: Справка**\n\n"
        "📁 **Управление кейсом**\n"
        "`/cases` - Выбрать кейс (КНОПКИ)\n"
        "`/case use <Name>` - Выбрать кейс (текстом)\n\n"

        "📄 **Документы**\n"
        "`/docs` - Показать список документов\n"
        "`/review <Title>` - Анализ документа (AI)\n"
        "`/doc delete <Title>` - Удалить документ (безвозвратно)\n"
        "*Загрузка:* Просто перетащите PDF/Word файл в чат.\n\n"

        "🧩 **Доказательства и Факты**\n"
        "`/evidence` - Показать факты по категориям (КНОПКИ)\n"
        "`/add_evidence <Tag> <Text>` - Добавить факт вручную\n"
        "_Пример:_ `/add_evidence Awards Золотая медаль 2023...`\n\n"

        "📚 **Справочник (USCIS RAG)**\n"
        "`/requirements` - Критерии EB-1A\n"
        "`/fees` - Актуальные пошлины\n"
        "`/filing` - Куда подавать (адреса)\n"
        "`/premium` - Premium Processing (I-907)\n"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")


# --- CASES (BUTTONS) ---
@bot.message_handler(commands=['cases'])
def handle_list_cases_buttons(message):
    with db_session() as session:
        cases = get_all_cases(session)
        if not cases:
            bot.reply_to(message, "📭 База пуста. Запустите `seed_cases.py`.")
            return

        markup = types.InlineKeyboardMarkup()
        for c in cases:
            # callback_data limit 64 bytes
            btn = types.InlineKeyboardButton(text=f"📂 {c.name}", callback_data=f"set_case:{c.name}")
            markup.add(btn)

        bot.send_message(message.chat.id, "Выберите активный кейс:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_case:'))
def callback_set_case(call):
    case_name = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)
    with db_session() as session:
        resp = set_active_case(session, chat_id, case_name)
        bot.answer_callback_query(call.id, "Кейс выбран!")
        bot.edit_message_text(f"✅ {resp}", chat_id, call.message.message_id, parse_mode="Markdown")


# --- EVIDENCE (BUTTONS) ---
@bot.message_handler(commands=['evidence'])
def handle_evidence_buttons(message):
    chat_id = str(message.chat.id)
    with db_session() as session:
        tags = get_evidence_tags(session, chat_id)

        if not tags:
            bot.reply_to(message, "📭 В этом кейсе пока нет доказательств.\nДобавьте их через `/add_evidence`.")
            return

        markup = types.InlineKeyboardMarkup()
        for tag in tags:
            # callback_data format: "view_ev:<Tag>"
            btn = types.InlineKeyboardButton(text=f"🏷 {tag}", callback_data=f"view_ev:{tag}")
            markup.add(btn)

        bot.send_message(chat_id, "Выберите категорию доказательств:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('view_ev:'))
def callback_view_evidence(call):
    tag = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)

    with db_session() as session:
        items = get_evidence_by_tag(session, chat_id, tag)

        # Формируем красивый список
        lines = [f"🏷 **Категория: {tag}** (Всего: {len(items)})", ""]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item.description}")
            if i >= 15:  # Ограничим вывод, чтобы не спамить
                lines.append(f"... и еще {len(items) - 15} фактов")
                break

        text_resp = "\n".join(lines)

        # Редактируем сообщение, заменяя кнопки на текст (или можно отправить новым)
        # Если текста слишком много, лучше отправить новым, но для кнопок удобно редактировать.
        # Чтобы не терять меню, можно оставить кнопки, но Telegram не разрешает текст > 4096 в caption.
        # Просто отредактируем.

        bot.answer_callback_query(call.id, "Загружаю факты...")

        # Добавим кнопку "Назад", чтобы вернуться к категориям
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_ev_tags")
        markup.add(back_btn)

        bot.edit_message_text(
            text=text_resp,
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )


@bot.callback_query_handler(func=lambda call: call.data == "back_to_ev_tags")
def callback_back_to_evidence(call):
    # Возвращаем меню категорий
    chat_id = str(call.message.chat.id)
    with db_session() as session:
        tags = get_evidence_tags(session, chat_id)
        markup = types.InlineKeyboardMarkup()
        for tag in tags:
            btn = types.InlineKeyboardButton(text=f"🏷 {tag}", callback_data=f"view_ev:{tag}")
            markup.add(btn)

        bot.edit_message_text(
            text="Выберите категорию доказательств:",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=markup
        )


# --- TEXT COMMANDS ---

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
def handle_case_use_text(message):
    text = message.text.strip()
    prefix = "/case use "
    if not text.startswith(prefix):
        bot.reply_to(message, "Формат: `/case use <Name>`", parse_mode="Markdown")
        return
    case_name = text[len(prefix):].strip()
    with db_session() as session:
        resp = set_active_case(session, str(message.chat.id), case_name)
        bot.reply_to(message, resp, parse_mode="Markdown")


@bot.message_handler(commands=['docs'])
def handle_list_docs(message):
    with db_session() as session:
        resp = cmd_list_documents(session, str(message.chat.id))
        bot.reply_to(message, resp, parse_mode="Markdown")


@bot.message_handler(commands=['doc'])
def handle_doc_commands(message):
    text = message.text.strip()
    if text.startswith("/doc delete "):
        title = text.replace("/doc delete ", "", 1).strip()
        with db_session() as session:
            resp = cmd_delete_document(session, str(message.chat.id), title)
            bot.reply_to(message, resp, parse_mode="Markdown")
    else:
        bot.reply_to(message, "Команда: `/doc delete <Title>`", parse_mode="Markdown")


@bot.message_handler(commands=['add_evidence'])
def handle_add_evidence(message):
    text = message.text.strip()
    prefix = "/add_evidence "
    if not text.startswith(prefix):
        bot.reply_to(message, "Формат: `/add_evidence <Tag> <Text>`", parse_mode="Markdown")
        return
    content = text[len(prefix):].strip()
    with db_session() as session:
        resp = cmd_add_manual_evidence(session, str(message.chat.id), content)
        bot.reply_to(message, resp, parse_mode="Markdown")


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
            if len(resp) > 4000:
                for x in range(0, len(resp), 4000):
                    bot.send_message(message.chat.id, resp[x:x + 4000], parse_mode="Markdown")
            else:
                bot.reply_to(message, resp, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")


@bot.message_handler(content_types=['document'])
def handle_files(message):
    try:
        chat_id = str(message.chat.id)
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name
        mime_type = message.document.mime_type or "application/octet-stream"

        bot.reply_to(message, "📥 Принял файл. Сохраняю...")
        with db_session() as session:
            result_text = save_document_upload(session, chat_id, file_name, downloaded_file, mime_type)
            bot.reply_to(message, result_text, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


if __name__ == "__main__":
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Bot crashed: {e}")
            time.sleep(5)