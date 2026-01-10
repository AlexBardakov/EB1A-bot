# app/telegram/commands_rag.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.llm.openai_client import OpenAIClient
from app.rag.retriever import retrieve_snippets
from app.storage.models import ChatState

# Системный промпт для простых ответов
RAG_SYSTEM = """You are an expert EB-1A immigration assistant.
Answer the user's question STRICTLY based on the provided Official USCIS Sources.
Rules:
- If the answer is in the sources, cite the specific source/section.
- If the answer is NOT in the sources, state "I cannot find this information in the official sources."
- Be concise and direct.
- Do NOT invent facts.
"""

def _get_chat(session: Session, chat_id: str) -> ChatState:
    from app.telegram.commands import get_or_create_chat_state
    return get_or_create_chat_state(session, chat_id)

def _simple_rag_query(session: Session, chat_id: str, query: str, user_prompt_template: str, kind_filter: list[str]) -> str:
    """
    Helper for single-shot RAG queries (cheaper and faster than debate).
    """
    # 1. Проверяем авторизацию (формально, хотя для справки кейс не всегда нужен, но оставим как было)
    cs = _get_chat(session, chat_id)
    if not cs.active_case_id:
         # Можно разрешить справку без кейса, но следуем логике "сначала выбери кейс"
        return "No active case selected. Use /case use <name> first."

    # 2. Ищем в базе
    rag_text = retrieve_snippets(
        session,
        query=query,
        kind_filter=kind_filter,
        top_k=8,
    )

    if not rag_text:
        return "I couldn't find relevant official information in my database."

    # 3. Формируем промпт
    user_msg = (
        f"{user_prompt_template}\n\n"
        f"=== OFFICIAL SOURCES ===\n{rag_text}"
    )

    # 4. Один вызов к OpenAI (GPT-4o)
    llm = OpenAIClient()
    result = llm.generate(
        system=RAG_SYSTEM,
        user=user_msg,
        temperature=0.1, # Минимум фантазии
        max_output_tokens=1000
    )

    return result.text

def cmd_requirements(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="EB-1A extraordinary ability requirements criteria two-step analysis",
        user_prompt_template="List the CURRENT EB-1A requirements and explain the two-step analysis based on the sources below.",
        kind_filter=["policy_manual", "cfr", "uscis_overview"]
    )

def cmd_fees(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="I-140 filing fee premium processing I-907 fee effective date",
        user_prompt_template="What are the current filing fees for Form I-140 and Premium Processing (I-907)? Check for any recent fee rule changes in the sources.",
        kind_filter=["fees", "form_i140", "form_i907"]
    )

def cmd_filing(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="Where to file I-140 direct filing addresses lockbox",
        user_prompt_template="Where should I file my I-140 petition? Provide the direct filing addresses or lockbox info based on the sources.",
        kind_filter=["filing", "form_i140"]
    )

def cmd_premium(session: Session, chat_id: str) -> str:
    return _simple_rag_query(
        session,
        chat_id,
        query="I-907 premium processing instructions I-140 eligibility",
        user_prompt_template="Explain how to request Premium Processing (I-907) for an EB-1A I-140 petition based on the sources.",
        kind_filter=["form_i907", "form_i140"]
    )