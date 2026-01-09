# app/telegram/commands.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.context_builder import build_context_pack
from app.core.orchestrator import run_debate
from app.llm.openai_client import OpenAIClient
from app.llm.gemini_client import GeminiClient
from app.storage.models import ChatState, RunMode, Document
from app.storage.models import Case


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
        return f"Case '{case_name}' not found."
    cs.active_case_id = case.id
    session.add(cs)
    return f"Active case set to: {case.name}"


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

    # Return the judge output (clean final)
    return f"Run #{result.run_id}\n\n{result.judge_output}"
