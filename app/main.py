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
from app.storage.models import EvidenceItem, EvidenceStatus
from app.telegram.commands import (
    set_active_case,
    cmd_review_document,
    cmd_list_documents,
    cmd_delete_document,
    cmd_add_manual_evidence,
    cmd_list_cases,
    get_all_cases,
    get_evidence_tags,
    get_evidence_by_tag,
    cmd_case_status,
    get_all_documents,
    cmd_link_evidence,
    STANDARD_CRITERIA,
    cmd_delete_evidence_by_code,
    update_evidence,
    EvidenceStatus,
    get_or_create_chat_state
)
from app.telegram.commands_rag import cmd_requirements, cmd_fees, cmd_filing, \
    cmd_premium
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
        "📊 **Дашборд**\n"
        "`/status` - Gap-анализ кейса (прогресс)\n\n"

        "🧩 **Доказательства (Факты)**\n"
        "`/add_evidence` - Добавить факт (Мастер)\n"
        "`/delete_evidence` - Удалить факт (Меню)\n"
        "`/evidence` - Просмотр фактов по тегам\n"
        "`/link` - Привязать Документ к Факту\n\n"

        "📁 **Файлы и Кейс**\n"
        "`/cases` - Выбрать кейс\n"
        "`/docs` - Список документов\n"
        "*Загрузка:* Просто перетащите файл в чат."
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")


# --- ADD EVIDENCE WIZARD ---
@bot.message_handler(commands=['add_evidence'])
def handle_add_evidence_wizard(message):
    """Шаг 1: Показываем кнопки с категориями."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for tag, desc_str in STANDARD_CRITERIA.items():
        # desc_str выглядит как "🏆 Награды (Prizes)"
        # callback_data: "add_ev_cat:Awards"
        buttons.append(types.InlineKeyboardButton(text=desc_str,
                                                  callback_data=f"add_ev_cat:{tag}"))

    markup.add(*buttons)
    bot.send_message(message.chat.id, "🧩 Выберите категорию для нового факта:",
                     reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('add_ev_cat:'))
def callback_add_evidence_cat(call):
    """Шаг 2: Категория выбрана, просим текст."""
    tag = call.data.split(':', 1)[1]

    msg = bot.edit_message_text(
        f"📝 Выбрана категория: **{STANDARD_CRITERIA.get(tag, tag)}**\n\n"
        f"Напишите текст доказательства в ответ на это сообщение (одним сообщением):",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )

    # Регистрируем следующий шаг - ожидание текста
    bot.register_next_step_handler(msg, process_evidence_text, tag)


def process_evidence_text(message, tag):
    """Шаг 3: Получаем текст и сохраняем."""
    chat_id = str(message.chat.id)
    description = message.text.strip()

    if not description:
        bot.send_message(chat_id,
                         "❌ Текст не может быть пустым. Попробуйте `/add_evidence` снова.")
        return

    with db_session() as session:
        resp = cmd_add_manual_evidence(session, chat_id, tag, description)
        bot.send_message(chat_id, resp, parse_mode="Markdown")


# --- DELETE EVIDENCE MENU ---
@bot.message_handler(commands=['delete_evidence'])
def handle_delete_evidence_menu(message):
    """Шаг 1: Показываем категории, где есть факты."""
    chat_id = str(message.chat.id)
    with db_session() as session:
        tags = get_evidence_tags(session, chat_id)
        if not tags:
            bot.reply_to(message, "📭 Фактов для удаления нет.")
            return

        markup = types.InlineKeyboardMarkup()
        for tag in tags:
            btn = types.InlineKeyboardButton(text=f"🗑 {tag}",
                                             callback_data=f"del_ev_tag:{tag}")
            markup.add(btn)

        bot.send_message(chat_id,
                         "Выберите категорию, из которой удалить факт:",
                         reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('del_ev_tag:'))
def callback_del_ev_tag(call):
    """Шаг 2: Показываем список фактов в категории."""
    tag = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)

    with db_session() as session:
        items = get_evidence_by_tag(session, chat_id, tag)
        if not items:
            bot.answer_callback_query(call.id, "В этой категории пусто.")
            return

        markup = types.InlineKeyboardMarkup()
        for item in items:
            # callback_data: "del_ev_do:MAN-1"
            label = f"❌ {item.exhibit_code}: {item.description[:20]}..."
            btn = types.InlineKeyboardButton(text=label,
                                             callback_data=f"del_ev_do:{item.exhibit_code}")
            markup.add(btn)

        # Кнопка назад
        markup.add(types.InlineKeyboardButton("🔙 Отмена",
                                              callback_data="cancel_action"))

        bot.edit_message_text(f"Выберите факт для УДАЛЕНИЯ из **{tag}**:",
                              chat_id, call.message.message_id,
                              reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('del_ev_do:'))
def callback_del_ev_perform(call):
    """Шаг 3: Удаляем."""
    ev_code = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)

    with db_session() as session:
        resp = cmd_delete_evidence_by_code(session, chat_id, ev_code)
        bot.answer_callback_query(call.id, "Удалено!")
        bot.edit_message_text(resp, chat_id, call.message.message_id,
                              parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == "cancel_action")
def callback_cancel(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)


# --- LINKING FLOW ---
@bot.message_handler(commands=['link'])
def handle_link_start(message):
    chat_id = str(message.chat.id)
    with db_session() as session:
        tags = get_evidence_tags(session, chat_id)
        if not tags:
            bot.reply_to(message, "📭 Нет фактов для привязки. `/add_evidence`")
            return
        markup = types.InlineKeyboardMarkup()
        for tag in tags:
            btn = types.InlineKeyboardButton(text=f"📂 {tag}",
                                             callback_data=f"link_cat:{tag}")
            markup.add(btn)
        bot.send_message(chat_id, "🔗 Шаг 1: Выберите категорию факта:",
                         reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('link_cat:'))
def callback_link_cat(call):
    tag = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)
    with db_session() as session:
        items = get_evidence_by_tag(session, chat_id, tag)
        markup = types.InlineKeyboardMarkup()
        for item in items:
            label = f"{item.exhibit_code} {item.description[:20]}..."
            btn = types.InlineKeyboardButton(text=label,
                                             callback_data=f"link_ev:{item.exhibit_code}")
            markup.add(btn)
        bot.edit_message_text(f"🔗 Шаг 2: Выберите факт из **{tag}**:", chat_id,
                              call.message.message_id, reply_markup=markup,
                              parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith('link_ev:'))
def callback_link_ev(call):
    ev_code = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)
    with db_session() as session:
        docs = get_all_documents(session, chat_id)
        if not docs:
            bot.answer_callback_query(call.id, "Нет документов!")
            return
        markup = types.InlineKeyboardMarkup()
        for d in docs:
            btn = types.InlineKeyboardButton(text=f"📄 {d.title}",
                                             callback_data=f"do_link:{ev_code}:{d.id}")
            markup.add(btn)
        bot.edit_message_text(
            f"🔗 Шаг 3: Какой документ подтверждает **{ev_code}**?", chat_id,
            call.message.message_id, reply_markup=markup,
            parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith('do_link:'))
def callback_do_link(call):
    _, ev_code, doc_id_str = call.data.split(':')
    with db_session() as session:
        resp = cmd_link_evidence(session, str(call.message.chat.id), ev_code,
                                 int(doc_id_str))
        bot.answer_callback_query(call.id, "Готово!")
        bot.edit_message_text(resp, call.message.chat.id,
                              call.message.message_id, parse_mode="Markdown")


# --- OTHER COMMANDS ---
@bot.message_handler(commands=['status'])
def handle_status(m):
    with db_session() as s: bot.reply_to(m, cmd_case_status(s, str(m.chat.id)),
                                         parse_mode="Markdown")


@bot.message_handler(commands=['cases'])
def handle_cases(message):
    with db_session() as session:
        cases = get_all_cases(session)
        markup = types.InlineKeyboardMarkup()
        for c in cases:
            markup.add(types.InlineKeyboardButton(text=f"📂 {c.name}",
                                                  callback_data=f"set_case:{c.name}"))
        bot.send_message(message.chat.id, "Выберите кейс:",
                         reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('set_case:'))
def callback_set_case(call):
    case_name = call.data.split(':', 1)[1]
    with db_session() as session:
        resp = set_active_case(session, str(call.message.chat.id), case_name)
        bot.answer_callback_query(call.id)
        bot.edit_message_text(f"✅ {resp}", call.message.chat.id,
                              call.message.message_id, parse_mode="Markdown")


@bot.message_handler(commands=['evidence'])
def handle_evidence_view(message):
    chat_id = str(message.chat.id)
    with db_session() as session:
        tags = get_evidence_tags(session, chat_id)
        if not tags:
            bot.reply_to(message, "📭 Нет фактов.")
            return
        markup = types.InlineKeyboardMarkup()
        for tag in tags:
            markup.add(types.InlineKeyboardButton(text=f"🏷 {tag}",
                                                  callback_data=f"view_ev:{tag}"))
        bot.send_message(chat_id, "Просмотр категорий:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('view_ev:'))
def callback_view_ev(call):
    """Показывает список фактов в категории в виде КНОПОК."""
    tag = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)

    with db_session() as session:
        items = get_evidence_by_tag(session, chat_id, tag)

        markup = types.InlineKeyboardMarkup(row_width=1)
        if not items:
            bot.answer_callback_query(call.id, "В этой категории пока пусто.")
            # Можно сразу предложить добавить
            # markup.add(types.InlineKeyboardButton("➕ Добавить", callback_data=f"add_ev_cat:{tag}"))

        for item in items:
            # Кнопка для каждого факта: "MAN-1: Текст..."
            # Обрезаем текст, чтобы влез в кнопку
            short_desc = (item.description[:30] + '..') if len(
                item.description) > 30 else item.description
            status_icon = "✅" if item.status == EvidenceStatus.verified else "📝"
            btn_text = f"{status_icon} {item.exhibit_code} | {short_desc}"

            # callback: open_ev:<CODE>
            markup.add(types.InlineKeyboardButton(btn_text,
                                                  callback_data=f"open_ev:{item.exhibit_code}"))

        markup.add(types.InlineKeyboardButton("🔙 Назад к категориям",
                                              callback_data="back_to_ev_tags"))

        bot.edit_message_text(
            f"📂 Категория: **{tag}**\nВыберите факт для редактирования:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )


# --- ДЕТАЛЬНЫЙ ПРОСМОТР И РЕДАКТОР ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('open_ev:'))
def callback_open_evidence(call):
    """Карточка факта с кнопками управления."""
    ev_code = call.data.split(':', 1)[1]
    chat_id = str(call.message.chat.id)

    with db_session() as session:
        # Ищем факт вручную или через helper (лучше напрямую для гибкости UI)
        cs = get_or_create_chat_state(session, chat_id)
        item = session.query(EvidenceItem).filter(
            EvidenceItem.case_id == cs.active_case_id,
            EvidenceItem.exhibit_code == ev_code
        ).one_or_none()

        if not item:
            bot.answer_callback_query(call.id,
                                      "Факт не найден (возможно, удален).")
            return

        # Формируем красивую карточку
        status_str = "VERIFIED (Готово)" if item.status == EvidenceStatus.verified else "DRAFT (Черновик)"
        # Визуализация силы: 1=🔴, 3=🟡, 5=🟢
        strength_icon = "🔴" if item.strength < 3 else (
            "🟡" if item.strength < 5 else "🟢")

        text = (
            f"🧾 **Факт: {item.exhibit_code}**\n"
            f"🏷 Теги: {', '.join(item.criterion_tags)}\n"
            f"➖➖➖➖➖➖\n"
            f"{item.description}\n"
            f"➖➖➖➖➖➖\n"
            f"📊 Сила: {strength_icon} **{item.strength}/5**\n"
            f"📌 Статус: **{status_str}**\n"
            f"📎 Документов привязано: {len(item.file_ids)}"
        )

        # Кнопки управления
        markup = types.InlineKeyboardMarkup(row_width=2)

        # Ряд 1: Редактировать текст
        markup.add(types.InlineKeyboardButton("✏️ Изменить текст",
                                              callback_data=f"edit_ev_txt:{ev_code}"))

        # Ряд 2: Сила и Статус
        btn_strength = types.InlineKeyboardButton(f"⭐ Сила ({item.strength})",
                                                  callback_data=f"set_ev_str_m:{ev_code}")

        # Логика переключения статуса одной кнопкой
        next_status = "verified" if item.status == EvidenceStatus.draft else "draft"
        btn_status_label = "✅ В Готово" if item.status == EvidenceStatus.draft else "📝 В Черновик"
        btn_status = types.InlineKeyboardButton(btn_status_label,
                                                callback_data=f"set_ev_stat:{ev_code}:{next_status}")

        markup.add(btn_strength, btn_status)

        # Ряд 3: Назад (нужно знать категорию, чтобы вернуться правильно.
        # Упростим: вернемся в корень evidence view)
        # Берем первый тег для возврата
        main_tag = item.criterion_tags[0] if item.criterion_tags else "Other"
        markup.add(types.InlineKeyboardButton("🔙 Назад к списку",
                                              callback_data=f"view_ev:{main_tag}"))

        bot.edit_message_text(text, chat_id, call.message.message_id,
                              reply_markup=markup, parse_mode="Markdown")


# --- ЛОГИКА ИЗМЕНЕНИЯ ТЕКСТА ---

@bot.callback_query_handler(
    func=lambda call: call.data.startswith('edit_ev_txt:'))
def callback_edit_text_start(call):
    ev_code = call.data.split(':', 1)[1]
    msg = bot.send_message(
        call.message.chat.id,
        f"✍️ Введите новое описание для факта **{ev_code}**:\n(Отправьте текст в ответ на это сообщение)"
    )
    bot.register_next_step_handler(msg, process_edit_text_finish, ev_code,
                                   call.message.message_id)


def process_edit_text_finish(message, ev_code, original_msg_id):
    chat_id = str(message.chat.id)
    new_text = message.text.strip()

    if not new_text:
        bot.send_message(chat_id, "❌ Текст не может быть пустым.")
        return

    with db_session() as session:
        update_evidence(session, chat_id, ev_code, description=new_text)
        # Удаляем сообщение пользователя и промпт бота для чистоты (опционально)
        # bot.delete_message(chat_id, message.message_id)

        bot.send_message(chat_id, f"✅ Описание факта {ev_code} обновлено!")

        # Можно попробовать обновить карточку, но проще отправить пользователя смотреть заново,
        # так как message_id изменился.
        # Или можно вызвать callback_open_evidence вручную, но это сложнее из step_handler.


# --- ЛОГИКА ИЗМЕНЕНИЯ СИЛЫ ---

@bot.callback_query_handler(
    func=lambda call: call.data.startswith('set_ev_str_m:'))
def callback_strength_menu(call):
    """Меню выбора оценки 1-5."""
    ev_code = call.data.split(':', 1)[1]
    markup = types.InlineKeyboardMarkup(row_width=5)
    btns = []
    for i in range(1, 6):
        btns.append(types.InlineKeyboardButton(str(i),
                                               callback_data=f"set_ev_str_v:{ev_code}:{i}"))
    markup.add(*btns)
    markup.add(types.InlineKeyboardButton("🔙 Отмена",
                                          callback_data=f"open_ev:{ev_code}"))

    bot.edit_message_text(
        f"📊 Оцените силу факта **{ev_code}** (1 - слабо, 5 - железобетонно):",
        call.message.chat.id, call.message.message_id, reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('set_ev_str_v:'))
def callback_strength_set(call):
    _, ev_code, val_str = call.data.split(':')
    chat_id = str(call.message.chat.id)

    with db_session() as session:
        update_evidence(session, chat_id, ev_code, strength=val_str)

    # Возвращаемся в карточку (эмулируем клик "Назад")
    # Трюк: подменяем data, чтобы callback_open_evidence сработал
    call.data = f"open_ev:{ev_code}"
    callback_open_evidence(call)


# --- ЛОГИКА ИЗМЕНЕНИЯ СТАТУСА ---

@bot.callback_query_handler(
    func=lambda call: call.data.startswith('set_ev_stat:'))
def callback_status_set(call):
    _, ev_code, new_status = call.data.split(':')
    chat_id = str(call.message.chat.id)

    with db_session() as session:
        update_evidence(session, chat_id, ev_code, status=new_status)

    # Возвращаемся в карточку
    call.data = f"open_ev:{ev_code}"
    callback_open_evidence(call)


@bot.callback_query_handler(func=lambda call: call.data == "back_to_ev_tags")
def callback_back(call):
    handle_evidence_view(call.message)


# --- RAG & DOCS ---
@bot.message_handler(commands=['requirements'])
def h_req(m):
    with db_session() as s: bot.reply_to(m,
                                         cmd_requirements(s, str(m.chat.id)),
                                         parse_mode="Markdown")


@bot.message_handler(commands=['docs'])
def h_docs(m):
    with db_session() as s: bot.reply_to(m,
                                         cmd_list_documents(s, str(m.chat.id)),
                                         parse_mode="Markdown")


@bot.message_handler(commands=['doc'])
def h_doc_del(m):
    if "/doc delete" in m.text:
        t = m.text.replace("/doc delete ", "").strip()
        with db_session() as s: bot.reply_to(m, cmd_delete_document(s,
                                                                    str(m.chat.id),
                                                                    t),
                                             parse_mode="Markdown")


@bot.message_handler(content_types=['document'])
def h_file(m):
    try:
        fi = bot.get_file(m.document.file_id)
        data = bot.download_file(fi.file_path)
        with db_session() as s:
            bot.reply_to(m, save_document_upload(s, str(m.chat.id),
                                                 m.document.file_name, data,
                                                 m.document.mime_type),
                         parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(m, f"Error: {e}")


if __name__ == "__main__":
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(e); time.sleep(5)