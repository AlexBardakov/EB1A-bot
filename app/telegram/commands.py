# app/telegram/commands.py
from __future__ import annotations

import os
import io
import zipfile

from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.context_builder import build_context_pack
from app.core.orchestrator import run_debate
from app.llm.openai_client import OpenAIClient
from app.llm.gemini_client import GeminiClient
from app.storage.models import ChatState, RunMode, Document, Case, \
    EvidenceItem, EvidenceStatus, Checkpoint

# --- КОНСТАНТЫ ---
STANDARD_CRITERIA: Dict[str, str] = {
    "Awards": "🏆 Награды (Prizes)",
    "Membership": "🤝 Членство (Membership)",
    "Media": "📰 Пресса (Media)",
    "Judging": "⚖️ Судейство (Judging)",
    "Contribution": "💡 Вклад (Contribution)",
    "Articles": "✍️ Статьи (Authorship)",
    "Exhibitions": "🎨 Выставки (Display)",
    "Leading Role": "🎭 Ведущая роль (Leading Role)",
    "Salary": "💰 Зарплата (High Salary)",
    "Commercial": "📈 Успех (Commercial Success)",
    "Other": "📁 Прочее (Other)"
}


# --- УТИЛИТЫ ---

def get_or_create_chat_state(session: Session, chat_id: str) -> ChatState:
    cs = session.query(ChatState).filter(
        ChatState.chat_id == chat_id).one_or_none()
    if cs:
        return cs
    cs = ChatState(chat_id=chat_id, active_case_id=None)
    session.add(cs)
    session.flush()
    return cs


def set_active_case(session: Session, chat_id: str, case_name: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    case = session.query(Case).filter(Case.name == case_name).one_or_none()
    if not case:
        return f"Case '{case_name}' not found. Check cases.json."
    cs.active_case_id = case.id
    session.add(cs)
    return f"Active case set to: **{case.name}**"


def get_all_cases(session: Session) -> list[Case]:
    """Возвращает объекты кейсов (для кнопок)."""
    return session.query(Case).all()


def cmd_list_cases(session: Session) -> str:
    """Возвращает текстовый список кейсов (было удалено случайно)."""
    cases = session.query(Case).all()
    if not cases:
        return "📭 База данных кейсов пуста."

    lines = ["📂 **Доступные кейсы:**\n"]
    for c in cases:
        lines.append(f"🔹 `{c.name}`")
    lines.append("\nДля выбора используйте меню `/cases`.")
    return "\n".join(lines)


# --- ДОКУМЕНТЫ ---

def get_all_documents(session: Session, chat_id: str) -> list[Document]:
    """Возвращает объекты документов (для меню связей)."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return []
    return session.query(Document).filter(
        Document.case_id == cs.active_case_id).all()


def cmd_list_documents(session: Session, chat_id: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    docs = (
        session.query(Document)
        .filter(Document.case_id == cs.active_case_id)
        .order_by(desc(Document.updated_at))
        .all()
    )

    if not docs:
        return "📂 В этом кейсе пока нет документов."

    lines = [f"📂 **Документы кейса (всего {len(docs)}):**\n"]
    for d in docs:
        v_count = len(d.versions)
        lines.append(f"📄 `{d.title}` (v{v_count})")

    return "\n".join(lines)


def cmd_delete_document(session: Session, chat_id: str, doc_title: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    doc = (
        session.query(Document)
        .filter(Document.case_id == cs.active_case_id,
                Document.title == doc_title)
        .one_or_none()
    )

    if not doc:
        return f"❌ Документ `{doc_title}` не найден."

    # Очистка ссылок перед удалением
    doc_id = doc.id
    linked_items = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == cs.active_case_id).all()

    cleaned_count = 0
    for item in linked_items:
        if item.file_ids and doc_id in item.file_ids:
            new_ids = [fid for fid in item.file_ids if fid != doc_id]
            item.file_ids = list(new_ids)
            cleaned_count += 1

    session.delete(doc)
    session.commit()

    msg = f"🗑 Документ `{doc_title}` удален."
    if cleaned_count > 0:
        msg += f"\n🔗 Автоматически отвязан от {cleaned_count} фактов."
    return msg


# --- ДОКАЗАТЕЛЬСТВА (EVIDENCE) ---

def get_evidence_tags(session: Session, chat_id: str) -> List[str]:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return []
    items = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == cs.active_case_id).all()
    unique_tags = set()
    for item in items:
        for tag in item.criterion_tags:
            unique_tags.add(tag)
    return sorted(list(unique_tags))


def get_evidence_by_tag(session: Session, chat_id: str, tag: str) -> List[
    EvidenceItem]:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return []
    items = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == cs.active_case_id).all()
    return [i for i in items if tag in i.criterion_tags]


def cmd_add_manual_evidence(session: Session, chat_id: str, category_tag: str,
                            description: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    count = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == cs.active_case_id).count()
    code = f"MAN-{count + 1}"

    item = EvidenceItem(
        case_id=cs.active_case_id,
        exhibit_code=code,
        title=f"Manual Entry ({category_tag})",
        description=description,
        criterion_tags=[category_tag],
        status=EvidenceStatus.draft,
        strength=3
    )
    session.add(item)
    session.commit()
    return f"✅ Добавлен факт **{code}** в категорию *{category_tag}*."


def cmd_delete_evidence_by_code(session: Session, chat_id: str,
                                ev_code: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    item = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == cs.active_case_id,
        EvidenceItem.exhibit_code == ev_code
    ).one_or_none()

    if not item:
        return f"❌ Факт с кодом `{ev_code}` не найден."

    session.delete(item)
    session.commit()
    return f"🗑 Факт `{ev_code}` успешно удален."


def cmd_link_evidence(session: Session, chat_id: str, ev_code: str,
                      doc_id: int) -> str:
    cs = get_or_create_chat_state(session, chat_id)

    item = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == cs.active_case_id,
        EvidenceItem.exhibit_code == ev_code
    ).one_or_none()

    doc = session.query(Document).filter(
        Document.case_id == cs.active_case_id,
        Document.id == doc_id
    ).one_or_none()

    if not item or not doc:
        return "❌ Ошибка: Факт или документ не найден."

    current_ids = set(item.file_ids)
    if doc.id in current_ids:
        return f"📎 Документ уже привязан к {ev_code}."

    current_ids.add(doc.id)
    item.file_ids = list(current_ids)
    session.commit()
    return f"🔗 Успешно! Документ `{doc.title}` привязан к факту `{ev_code}`."


# --- DASHBOARD & REVIEW ---

def cmd_case_status(session: Session, chat_id: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран. Используйте `/cases`."

    case = session.query(Case).filter(Case.id == cs.active_case_id).one()
    items = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == case.id).all()
    docs = session.query(Document).filter(Document.case_id == case.id).all()

    grouped = {tag: [] for tag in STANDARD_CRITERIA.keys()}
    grouped["Other"] = []

    for item in items:
        tags = item.criterion_tags or ["Other"]
        for tag in tags:
            target_key = tag if tag in STANDARD_CRITERIA else "Other"
            grouped[target_key].append(item)

    lines = [f"📊 **GAP-АНАЛИЗ КЕЙСА: {case.name}**", ""]

    lines.append(
        f"📁 **Файлы:** {len(docs)} шт." if docs else "📁 **Файлы:** 0 ⚠️")
    lines.append("")
    lines.append("🧩 **Критерии EB-1A:**")

    for tag, desc_str in STANDARD_CRITERIA.items():
        ev_list = grouped[tag]
        clean_name = desc_str.split(" ", 1)[1] if " " in desc_str else desc_str

        if not ev_list:
            lines.append(f"🔴 **{tag}** — ПУСТО")
        else:
            avg_strength = sum(i.strength for i in ev_list) / len(ev_list)
            icon = "🟢" if avg_strength >= 4 else "🟡"
            lines.append(f"{icon} **{tag}** ({len(ev_list)} фактов)")
            for item in ev_list:
                status = "✅" if item.status == EvidenceStatus.verified else "📝"
                desc = (item.description[:35] + '..') if len(
                    item.description) > 35 else item.description
                links_str = f" (📎 {len(item.file_ids)})" if item.file_ids else ""
                lines.append(
                    f"   └ {status} `{item.exhibit_code}`: {desc}{links_str}")

    if grouped["Other"]:
        lines.append("")
        lines.append(f"📂 **Прочее:** {len(grouped['Other'])} фактов")
        for item in grouped["Other"]:
            lines.append(
                f"   └ `{item.exhibit_code}`: {item.description[:40]}")

    return "\n".join(lines)


def cmd_review_document(session: Session, chat_id: str,
                        document_title: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "No active case. Use /case use <name> first."

    doc = (
        session.query(Document)
        .filter(Document.case_id == cs.active_case_id,
                Document.title == document_title)
        .one_or_none()
    )
    if not doc:
        return f"Document '{document_title}' not found in active case."

    ctx = build_context_pack(session, cs.active_case_id, document_id=doc.id,
                             include_document_text=True)
    llm_a = OpenAIClient()
    llm_b = GeminiClient(model_name="gemini-2.5-pro")

    task = "Review the provided document for EB-1A strength and weaknesses."
    result = run_debate(session, ctx=ctx, mode=RunMode.review, user_task=task,
                        llm_a=llm_a, llm_b=llm_b, judge=llm_a)
    return f"Run #{result.run_id}\n\n{result.judge_output}"


def update_evidence(session: Session, chat_id: str, ev_code: str,
                    **kwargs) -> str:
    """Обновляет поля факта: description, strength, status."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    item = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == cs.active_case_id,
        EvidenceItem.exhibit_code == ev_code
    ).one_or_none()

    if not item:
        return f"❌ Факт `{ev_code}` не найден."

    # Обновляем поля, если они переданы
    if "description" in kwargs:
        item.description = kwargs["description"]

    if "strength" in kwargs:
        # Валидация 1..5
        val = int(kwargs["strength"])
        item.strength = max(1, min(5, val))

    if "status" in kwargs:
        # Ожидаем string: 'draft', 'verified', 'archived'
        new_status = kwargs["status"]
        # Можно добавить проверку на Enum, но SQLAlchemy сам ругнется если что
        item.status = EvidenceStatus(new_status)

    session.commit()
    # Возвращаем обновленный объект (или строку, но лучше строку для UI)
    return f"✅ Факт `{ev_code}` успешно обновлен."


def cmd_get_memo_data(session: Session, chat_id: str):
    """Возвращает данные memo для отображения."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return None, "⚠️ Кейс не выбран."

    case = session.query(Case).filter(Case.id == cs.active_case_id).one()
    return case.memo_json, case.name


def cmd_update_memo_field(session: Session, chat_id: str, key: str,
                          value_text: str) -> str:
    """Обновляет конкретное поле в JSON memo."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    case = session.query(Case).filter(Case.id == cs.active_case_id).one()

    # Копируем текущий dict, чтобы SQLAlchemy увидел изменение
    new_memo = dict(case.memo_json)

    # Обработка списков (например, pillars)
    if key == "pillars":
        # Разбиваем текст по строкам
        lines = [line.strip() for line in value_text.split('\n') if
                 line.strip()]
        new_memo[key] = lines
    else:
        new_memo[key] = value_text.strip()

    case.memo_json = new_memo
    session.commit()

    return f"✅ Поле **{key}** успешно обновлено!"

def cmd_search_evidence(session: Session, chat_id: str, query_str: str) -> List[EvidenceItem]:
    """Ищет факты по вхождению текста в description или exhibit_code."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return []

    # Используем ILIKE для поиска без учета регистра
    items = (
        session.query(EvidenceItem)
        .filter(
            EvidenceItem.case_id == cs.active_case_id,
            EvidenceItem.description.ilike(f"%{query_str}%")
        )
        .order_by(EvidenceItem.exhibit_code)
        .limit(15) # Ограничиваем выдачу, чтобы не сломать интерфейс
        .all()
    )
    return items


# --- CHECKPOINTS (БЭКАПЫ) ---

def cmd_create_checkpoint(session: Session, chat_id: str, label: str) -> str:
    """Создает снимок состояния кейса (Memo + Evidence)."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    # 1. Собираем данные
    case = session.query(Case).filter(Case.id == cs.active_case_id).one()

    # Сериализуем факты в список словарей
    evidence_items = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == case.id).all()
    evidence_dump = []
    for item in evidence_items:
        evidence_dump.append({
            "exhibit_code": item.exhibit_code,
            "title": item.title,
            "description": item.description,
            "criterion_tags": item.criterion_tags,
            "strength": item.strength,
            "status": item.status.value,  # Enum to string
            "file_ids": item.file_ids
        })

    # Формируем полный снапшот
    snapshot = {
        "memo_json": case.memo_json,
        "evidence_items": evidence_dump,
        "timestamp": datetime.utcnow().isoformat()
    }

    # 2. Сохраняем в БД
    cp = Checkpoint(
        case_id=case.id,
        label=label,
        snapshot_json=snapshot
    )
    session.add(cp)
    session.commit()

    return f"💾 Чекпоинт **'{label}'** успешно создан!"


def get_checkpoints_list(session: Session, chat_id: str):
    """Возвращает список чекпоинтов для кейса."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return []

    return (
        session.query(Checkpoint)
        .filter(Checkpoint.case_id == cs.active_case_id)
        .order_by(desc(Checkpoint.created_at))
        .limit(10)
        .all()
    )


def cmd_restore_checkpoint(session: Session, chat_id: str,
                           checkpoint_id: int) -> str:
    """Откатывает кейс к состоянию чекпоинта."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    cp = session.query(Checkpoint).filter(
        Checkpoint.id == checkpoint_id).one_or_none()
    if not cp:
        return "❌ Чекпоинт не найден."

    if cp.case_id != cs.active_case_id:
        return "❌ Ошибка доступа: чекпоинт от другого кейса."

    snap = cp.snapshot_json
    case = session.query(Case).filter(Case.id == cs.active_case_id).one()

    # 1. Восстанавливаем Memo
    if "memo_json" in snap:
        case.memo_json = snap["memo_json"]

    # 2. Восстанавливаем Факты (Evidence)
    # Сначала удаляем текущие
    session.query(EvidenceItem).filter(
        EvidenceItem.case_id == case.id).delete()

    # Создаем заново из бэкапа
    ev_data_list = snap.get("evidence_items", [])
    for ev_data in ev_data_list:
        new_item = EvidenceItem(
            case_id=case.id,
            exhibit_code=ev_data["exhibit_code"],
            title=ev_data.get("title", ""),
            description=ev_data["description"],
            criterion_tags=ev_data["criterion_tags"],
            strength=ev_data["strength"],
            status=EvidenceStatus(ev_data["status"]),  # String to Enum
            file_ids=ev_data["file_ids"]
        )
        session.add(new_item)

    session.commit()
    return f"♻️ Кейс успешно восстановлен к состоянию: **{cp.label}**"


def cmd_export_case_archive(session: Session, chat_id: str):
    """
    Создает ZIP-архив, где файлы разложены по папкам категорий.
    Включает только АКТИВНЫЕ версии документов.
    """
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return None, "⚠️ Кейс не выбран."

    case = session.query(Case).filter(Case.id == cs.active_case_id).one()

    # 1. Собираем карту: Document ID -> Набор папок (тегов)
    # По умолчанию документ нигде не лежит
    doc_folders = {}  # {doc_id: set(["Awards", "Media"])}

    evidence_items = session.query(EvidenceItem).filter(
        EvidenceItem.case_id == case.id).all()

    for item in evidence_items:
        # Получаем теги факта (это и будут названия папок)
        tags = item.criterion_tags or ["Others"]

        # Получаем ID привязанных документов
        linked_ids = item.file_ids or []

        for doc_id in linked_ids:
            if doc_id not in doc_folders:
                doc_folders[doc_id] = set()
            # Добавляем все теги факта к этому документу
            for tag in tags:
                doc_folders[doc_id].add(tag)

    # 2. Получаем все документы кейса
    documents = session.query(Document).filter(
        Document.case_id == case.id).all()

    if not documents:
        return None, "📭 В кейсе нет документов для выгрузки."

    # 3. Формируем ZIP в памяти
    memory_file = io.BytesIO()

    # Флаг, чтобы понять, добавили ли мы хоть что-то
    files_added = 0

    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc in documents:
            # Пропускаем, если нет текущей версии (битая запись)
            if not doc.current_version or not doc.current_version.storage_url:
                continue

            file_path = doc.current_version.storage_url

            # Проверяем, существует ли файл физически
            if not os.path.exists(file_path):
                # Можно логировать ошибку, но пока просто пропустим
                continue

            # Определяем целевые папки
            target_folders = doc_folders.get(doc.id, set())

            if not target_folders:
                target_folders.add("Others")

            # Добавляем файл в каждую целевую папку архива
            for folder in target_folders:
                # Очищаем имя папки от спецсимволов (на всякий случай)
                safe_folder = "".join(
                    c for c in folder if c.isalnum() or c in " _-").strip()
                archive_path = f"{safe_folder}/{doc.title}"

                # Пишем файл
                zf.write(file_path, arcname=archive_path)
                files_added += 1

    if files_added == 0:
        return None, "⚠️ Файлы физически не найдены на диске (возможно, были удалены вручную)."

    memory_file.seek(0)
    filename = f"Case_Files_{case.name.replace(' ', '_')}.zip"

    return memory_file, filename