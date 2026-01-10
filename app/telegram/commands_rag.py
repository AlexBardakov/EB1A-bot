# app/telegram/commands_rag.py
from __future__ import annotations

from sqlalchemy.orm import Session
from app.llm.openai_client import OpenAIClient
from app.rag.retriever import retrieve_snippets
from app.storage.models import ChatState

# --- ИЗМЕНЕНИЕ: Добавили инструкцию про русский язык ---
RAG_SYSTEM = """You are an expert EB-1A immigration assistant.
Your goal is to help the user understand complex US immigration rules.

IMPORTANT:
1. Base your answer STRICTLY on the provided Official USCIS Sources.
2. If the answer is in the sources, cite them.
3. If the answer is NOT in the sources, say "В официальных источниках нет информации об этом."
4. ALWAYS answer in RUSSIAN language, regardless of the source language.
5. Translate legal terms correctly (e.g., "Petitioner" -> "Петиционер/Заявитель", "Beneficiary" -> "Бенефициар").
"""

def _get_chat(session: Session, chat_id: str) -> ChatState:
    from app.telegram.commands import get_or_create_chat_state
    return get_or_create_chat_state(session, chat_id)

def _simple_rag_query(session: Session, chat_id: str, query: str, user_prompt_template: str, kind_filter: list[str]) -> str:
    """
    Helper for single-shot RAG queries (cheaper and faster than debate).
    """
    cs = _get_chat(session, chat_id)
    if not cs.active_case_id:
        return "Сначала выберите кейс с помощью команды /case use <Name>"

    # 1. Ищем в базе (источники на английском)
    rag_text = retrieve_snippets(
        session,
        query=query,
        kind_filter=kind_filter,
        top_k=8,
    )

    if not rag_text:
        return "К сожалению, я не нашел информации в официальных источниках."

    # 2. Формируем промпт
    user_msg = (
        f"{user_prompt_template}\n\n"
        f"=== OFFICIAL SOURCES (ENGLISH) ===\n{rag_text}"
    )

    # 3. Один вызов к OpenAI (GPT-4o)
    llm = OpenAIClient()
    result = llm.generate(
        system=RAG_SYSTEM,
        user=user_msg,
        temperature=0.1,
        max_output_tokens=1500 # Чуть больше токенов для перевода
    )

    return result.text

# --- ИЗМЕНЕНИЕ: Вопросы в функциях тоже лучше адаптировать,
# хотя LLM поймет и так, но для точности поиска оставим query на английском,
# а user_prompt_template дадим понять контекст.

def cmd_requirements(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="EB-1A extraordinary ability requirements criteria two-step analysis",
        user_prompt_template="Перечисли текущие требования EB-1A и объясни 'two-step analysis' на основе источников.",
        kind_filter=["policy_manual", "cfr", "uscis_overview"]
    )

def cmd_fees(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="I-140 filing fee premium processing I-907 fee effective date",
        user_prompt_template="Какие сейчас пошлины (Filing Fees) для форм I-140 и I-907 (Premium)?",
        kind_filter=["fees", "form_i140", "form_i907"]
    )

def cmd_filing(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="Where to file I-140 direct filing addresses lockbox",
        user_prompt_template="Куда нужно подавать петицию I-140? Укажи адреса (Lockbox) из источников.",
        kind_filter=["filing", "form_i140"]
    )

def cmd_premium(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="I-907 premium processing instructions I-140 eligibility",
        user_prompt_template="Объясни, как запросить Premium Processing (I-907) для EB-1A.",
        kind_filter=["form_i907", "form_i140"]
    )