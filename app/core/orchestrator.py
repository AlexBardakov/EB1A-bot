# app/core/orchestrator.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session

from app.core.context_builder import ContextPack
from app.llm.base import LLMClient
from app.storage.models import Run, RunMode


ANALYST_SYSTEM = """You are an EB-1A legal analyst.
Work strictly within the provided Case Memo and Evidence Registry.
Apply the two-step USCIS analysis:
1) Initial evidence criteria
2) Final merits determination

Rules:
- Do NOT invent facts, documents, or sources.
- Do NOT change the Field of Endeavor or case goal unless explicitly instructed via a command.
- If information is missing, say so and ask for the minimal missing piece.
Output must be structured and concise.
"""

CRITIC_SYSTEM = """You are an EB-1A RFE-style reviewer (strict).
Your job is to find weaknesses, inconsistencies, and RFE risks.

Rules:
- Assume the officer is skeptical.
- Flag overbroad claims, missing proof, and replaceability arguments.
- Suggest evidence/edits that reduce risk.
- Do NOT invent facts or sources.
Output must be: Issues / Fixes / Questions / Confidence(0-100).
"""

JUDGE_SYSTEM = """You are a neutral EB-1A adjudication summarizer.
Combine the best parts of both sides and produce:
1) Verdict: PASS / NEEDS WORK
2) Strengths (bullets)
3) Risks (bullets)
4) Next steps (max 10 bullets)
Rules:
- Do NOT invent facts or sources.
- Keep it short and actionable.
"""


@dataclass
class OrchestratorResult:
    model_a_output: str
    model_b_output: str
    critique_a: str
    critique_b: str
    judge_output: str
    run_id: int


def _hash_inputs(payload: Dict[str, Any]) -> str:
    raw = repr(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _render_user_prompt(
    ctx: ContextPack,
    user_task: str,
    *,
    mode: RunMode,
    rag_snippets: Optional[str] = None,
) -> str:
    memo = ctx.memo_json or {}
    memo_en = memo.get("en") or memo.get("memo_en") or ""
    memo_ru = memo.get("ru") or memo.get("memo_ru") or ""

    lock_line = "LOCK_MODE=ON (Do not change field/goal)." if ctx.lock_mode else "LOCK_MODE=OFF."

    parts = [
        f"CASE: {ctx.case_name} (id={ctx.case_id})",
        lock_line,
        "",
        "=== CASE MEMO (EN) ===",
        memo_en.strip() or "[no memo_en set]",
        "",
        "=== CASE MEMO (RU) ===",
        memo_ru.strip() or "[no memo_ru set]",
        "",
        "=== EVIDENCE REGISTRY (summary) ===",
        ctx.evidence_summary or "[no exhibits yet]",
    ]

    if rag_snippets:
        parts += ["", "=== OFFICIAL SOURCES (RAG SNIPPETS) ===", rag_snippets]

    if ctx.document_text:
        parts += ["", "=== DOCUMENT TEXT ===", ctx.document_text]

    parts += ["", "=== TASK ===", user_task.strip(), "", f"MODE={mode.value}"]
    return "\n".join(parts)


def run_debate(
    session: Session,
    *,
    ctx: ContextPack,
    mode: RunMode,
    user_task: str,
    llm_a: LLMClient,
    llm_b: LLMClient,
    judge: Optional[LLMClient] = None,
    rag_snippets: Optional[str] = None,
    temperature: float = 0.2,
    max_output_tokens: int = 1400,
) -> OrchestratorResult:
    """
    2-model debate with cross-critique + final judge.
    Stores a Run row for audit/debug.
    """
    if judge is None:
        # Default: use model A as judge (works fine for MVP)
        judge = llm_a

    prompt_pack = {
        "case_id": ctx.case_id,
        "case_name": ctx.case_name,
        "mode": mode.value,
        "lock_mode": ctx.lock_mode,
        "has_document_text": bool(ctx.document_text),
        "user_task": user_task,
        "rag_included": bool(rag_snippets),
        "providers": {"a": llm_a.name, "b": llm_b.name, "judge": judge.name},
    }
    inputs_hash = _hash_inputs(prompt_pack)

    # 1) Initial answers
    user_prompt = _render_user_prompt(ctx, user_task, mode=mode, rag_snippets=rag_snippets)

    a0 = llm_a.generate(
        system=ANALYST_SYSTEM,
        user=user_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    b0 = llm_b.generate(
        system=ANALYST_SYSTEM,
        user=user_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    # 2) Cross-critique
    a_crit_user = (
        user_prompt
        + "\n\n=== OTHER MODEL ANSWER (B) ===\n"
        + (b0.text or "")
        + "\n\nNow critique the OTHER MODEL answer strictly."
    )
    b_crit_user = (
        user_prompt
        + "\n\n=== OTHER MODEL ANSWER (A) ===\n"
        + (a0.text or "")
        + "\n\nNow critique the OTHER MODEL answer strictly."
    )

    a1 = llm_a.generate(
        system=CRITIC_SYSTEM,
        user=a_crit_user,
        temperature=0.1,
        max_output_tokens=900,
    )
    b1 = llm_b.generate(
        system=CRITIC_SYSTEM,
        user=b_crit_user,
        temperature=0.1,
        max_output_tokens=900,
    )

    # 3) Judge synthesis
    judge_user = (
        user_prompt
        + "\n\n=== MODEL A ANSWER ===\n"
        + (a0.text or "")
        + "\n\n=== MODEL B ANSWER ===\n"
        + (b0.text or "")
        + "\n\n=== MODEL A CRITIQUE OF B ===\n"
        + (a1.text or "")
        + "\n\n=== MODEL B CRITIQUE OF A ===\n"
        + (b1.text or "")
        + "\n\nSynthesize a final answer per your instructions."
    )

    j = judge.generate(
        system=JUDGE_SYSTEM,
        user=judge_user,
        temperature=0.2,
        max_output_tokens=900,
    )

    run = Run(
        case_id=ctx.case_id,
        mode=mode,
        inputs_hash=inputs_hash,
        prompt_pack=prompt_pack,
        model_a_output=a0.text or "",
        model_b_output=b0.text or "",
        critique_a=a1.text or "",
        critique_b=b1.text or "",
        judge_output=j.text or "",
    )
    session.add(run)
    session.flush()  # get run.id without commit

    return OrchestratorResult(
        model_a_output=run.model_a_output,
        model_b_output=run.model_b_output,
        critique_a=run.critique_a,
        critique_b=run.critique_b,
        judge_output=run.judge_output,
        run_id=run.id,
    )
