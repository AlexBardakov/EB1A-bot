# app/telegram/commands_rag.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.context_builder import build_context_pack
from app.core.orchestrator import run_debate
from app.llm.openai_client import OpenAIClient
from app.llm.gemini_client import GeminiClient
from app.rag.retriever import retrieve_snippets
from app.storage.models import ChatState, RunMode


def _get_chat(session: Session, chat_id: str) -> ChatState:
    from app.telegram.commands import get_or_create_chat_state
    return get_or_create_chat_state(session, chat_id)


def cmd_requirements(session: Session, chat_id: str) -> str:
    cs = _get_chat(session, chat_id)
    if not cs.active_case_id:
        return "No active case. Use /case use <name> first."

    ctx = build_context_pack(session, cs.active_case_id, include_document_text=False)

    llm_a = OpenAIClient()
    llm_b = GeminiClient()

    rag = retrieve_snippets(
        session,
        query="EB-1A extraordinary ability requirements, two-step analysis, criteria list, final merits determination",
        kind_filter=["policy_manual", "cfr", "uscis_overview"],
        top_k=10,
    )

    task = (
        "Provide the CURRENT EB-1A (Extraordinary Ability) requirements and the two-step analysis. "
        "Use ONLY the provided RAG snippets for factual/legal statements. "
        "If a detail is not supported by snippets, explicitly say it is not confirmed."
    )

    res = run_debate(
        session,
        ctx=ctx,
        mode=RunMode.requirements,
        user_task=task,
        llm_a=llm_a,
        llm_b=llm_b,
        judge=llm_a,          # ✅ judge = OpenAI
        rag_snippets=rag,
        temperature=0.2,
    )
    return f"Run #{res.run_id}\n\n{res.judge_output}"


def cmd_fees(session: Session, chat_id: str) -> str:
    cs = _get_chat(session, chat_id)
    if not cs.active_case_id:
        return "No active case. Use /case use <name> first."

    ctx = build_context_pack(session, cs.active_case_id, include_document_text=False)

    llm_a = OpenAIClient()
    llm_b = GeminiClient()

    rag = retrieve_snippets(
        session,
        query="USCIS fees for I-140 and premium processing I-907 and how to calculate or verify current fees",
        kind_filter=["fees", "form_i140", "form_i907"],
        top_k=10,
    )

    task = (
        "Explain how to find and verify CURRENT USCIS filing fees relevant to I-140 and premium processing (I-907). "
        "Do not guess numbers if not present. Prefer directing to Fee Calculator / official fee pages in the snippets. "
        "Include any 'effective date' style guidance if present in snippets."
    )

    res = run_debate(
        session,
        ctx=ctx,
        mode=RunMode.fees,
        user_task=task,
        llm_a=llm_a,
        llm_b=llm_b,
        judge=llm_a,          # ✅ judge = OpenAI
        rag_snippets=rag,
        temperature=0.2,
    )
    return f"Run #{res.run_id}\n\n{res.judge_output}"


def cmd_filing(session: Session, chat_id: str) -> str:
    cs = _get_chat(session, chat_id)
    if not cs.active_case_id:
        return "No active case. Use /case use <name> first."

    ctx = build_context_pack(session, cs.active_case_id, include_document_text=False)

    llm_a = OpenAIClient()
    llm_b = GeminiClient()

    rag = retrieve_snippets(
        session,
        query="How to file Form I-140, where to file, online filing, direct filing addresses, EB-1A",
        kind_filter=["form_i140", "filing"],
        top_k=10,
    )

    task = (
        "Describe CURRENT filing options for I-140 (where/how to file, addresses/online notes) "
        "based ONLY on the provided snippets. If addresses are not in snippets, say so and "
        "instruct how to locate them from USCIS pages referenced."
    )

    res = run_debate(
        session,
        ctx=ctx,
        mode=RunMode.filing,
        user_task=task,
        llm_a=llm_a,
        llm_b=llm_b,
        judge=llm_a,          # ✅ judge = OpenAI
        rag_snippets=rag,
        temperature=0.2,
    )
    return f"Run #{res.run_id}\n\n{res.judge_output}"


def cmd_premium(session: Session, chat_id: str) -> str:
    cs = _get_chat(session, chat_id)
    if not cs.active_case_id:
        return "No active case. Use /case use <name> first."

    ctx = build_context_pack(session, cs.active_case_id, include_document_text=False)

    llm_a = OpenAIClient()
    llm_b = GeminiClient()

    rag = retrieve_snippets(
        session,
        query="How to request premium processing for I-140 using Form I-907, filing method, rules",
        kind_filter=["form_i907", "form_i140"],
        top_k=10,
    )

    task = (
        "Explain CURRENT premium processing request mechanics relevant to I-140 using I-907. "
        "Use only provided snippets; do not guess. Provide a short checklist."
    )

    res = run_debate(
        session,
        ctx=ctx,
        mode=RunMode.premium,
        user_task=task,
        llm_a=llm_a,
        llm_b=llm_b,
        judge=llm_a,          # ✅ judge = OpenAI
        rag_snippets=rag,
        temperature=0.2,
    )
    return f"Run #{res.run_id}\n\n{res.judge_output}"
