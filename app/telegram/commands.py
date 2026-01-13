# app/telegram/commands.py
from __future__ import annotations

from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.context_builder import build_context_pack
from app.core.orchestrator import run_debate
from app.llm.openai_client import OpenAIClient
from app.llm.gemini_client import GeminiClient
from app.storage.models import ChatState, RunMode, Document, Case, EvidenceItem, EvidenceStatus


def get_or_create_chat_state(session: Session, chat_id: str) -> ChatState:
    cs = session.query(ChatState).filter(ChatState.chat_id == chat_id).one_or_none()
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
    """Возвращает список всех кейсов (объектов) для создания кнопок."""
    return session.query(Case).all()


def cmd_list_cases(session: Session) -> str:
    """Текстовая версия списка кейсов."""
    cases = session.query(Case).all()
    if not cases:
        return "📭 База данных кейсов пуста. Пожалуйста, запустите `python scripts/seed_cases.py`"

    lines = ["📂 **Доступные кейсы:**\n"]
    for c in cases:
        lines.append(f"🔹 `{c.name}`")

    lines.append("\nДля выбора используйте команду `/cases` (кнопки).")
    return "\n".join(lines)


# --- ДОКУМЕНТЫ ---

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
        .filter(Document.case_id == cs.active_case_id, Document.title == doc_title)
        .one_or_none()
    )

    if not doc:
        return f"❌ Документ `{doc_title}` не найден."

    session.delete(doc)
    session.commit()
    return f"🗑 Документ `{doc_title}` успешно удален."


# --- ДОКАЗАТЕЛЬСТВА (EVIDENCE) ---

def cmd_add_manual_evidence(session: Session, chat_id: str, text_input: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "⚠️ Кейс не выбран."

    parts = text_input.split(" ", 1)
    if len(parts) < 2:
        return "⚠️ Формат: `/add_evidence <Tag> <Text>`"

    category_tag = parts[0].strip()
    description = parts[1].strip()

    count = session.query(EvidenceItem).filter(EvidenceItem.case_id == cs.active_case_id).count()
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


def get_evidence_tags(session: Session, chat_id: str) -> List[str]:
    """Собирает уникальные теги (категории) из всех доказательств кейса."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return []

    # Берем все EvidenceItems и собираем теги в Python (проще и надежнее для JSON списков)
    items = session.query(EvidenceItem).filter(EvidenceItem.case_id == cs.active_case_id).all()
    unique_tags = set()
    for item in items:
        for tag in item.criterion_tags:
            unique_tags.add(tag)

    return sorted(list(unique_tags))


def get_evidence_by_tag(session: Session, chat_id: str, tag: str) -> List[EvidenceItem]:
    """Возвращает список фактов, у которых есть указанный тег."""
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return []

    # Фильтруем на уровне Python, так как JSON contains в разных диалектах SQL может отличаться
    items = session.query(EvidenceItem).filter(EvidenceItem.case_id == cs.active_case_id).all()
    filtered = [i for i in items if tag in i.criterion_tags]
    return filtered


# --- REVIEW ---

def cmd_review_document(session: Session, chat_id: str, document_title: str) -> str:
    cs = get_or_create_chat_state(session, chat_id)
    if not cs.active_case_id:
        return "No active case. Use /case use <name> first."

    doc = (
        session.query(Document)
        .filter(Document.case_id == cs.active_case_id, Document.title == document_title)
        .one_or_none()
    )
    if not doc:
        return f"Document '{document_title}' not found in active case."

    ctx = build_context_pack(session, cs.active_case_id, document_id=doc.id, include_document_text=True)

    llm_a = OpenAIClient()
    llm_b = GeminiClient()

    task = (
        "Review the provided document for EB-1A strength and weaknesses. "
        "Find missing evidence links to exhibits, overbroad claims, inconsistencies, and suggest edits."
    )

    result = run_debate(
        session,
        ctx=ctx,
        mode=RunMode.review,
        user_task=task,
        llm_a=llm_a,
        llm_b=llm_b,
        judge=llm_a,
    )

    return f"Run #{result.run_id}\n\n{result.judge_output}"