# app/core/context_builder.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.storage.models import Case, EvidenceItem, Document, DocumentVersion


@dataclass
class ContextPack:
    case_id: int
    case_name: str
    lock_mode: bool
    memo_json: Dict[str, Any]
    evidence_summary: str
    document_text: Optional[str]
    extra: Dict[str, Any]


def _summarize_evidence(evidence_items: List[EvidenceItem], max_items: int = 40) -> str:
    """
    Keep it short to avoid token bloat; the point is consistent referencing.
    """
    lines = []
    for e in evidence_items[:max_items]:
        tags = ", ".join(e.criterion_tags or [])
        lines.append(f"- {e.exhibit_code}: {e.title} | tags=[{tags}] | status={e.status.value} | strength={e.strength}")
    if len(evidence_items) > max_items:
        lines.append(f"... ({len(evidence_items) - max_items} more exhibits not shown)")
    return "\n".join(lines).strip()


def build_context_pack(
    session: Session,
    case_id: int,
    *,
    document_id: Optional[int] = None,
    document_version_id: Optional[int] = None,
    include_document_text: bool = True,
) -> ContextPack:
    case: Case | None = session.get(Case, case_id)
    if not case:
        raise ValueError(f"Case {case_id} not found")

    evidence_items = (
        session.query(EvidenceItem)
        .filter(EvidenceItem.case_id == case_id)
        .order_by(EvidenceItem.exhibit_code.asc())
        .all()
    )
    evidence_summary = _summarize_evidence(evidence_items)

    doc_text: Optional[str] = None
    if include_document_text and (document_id or document_version_id):
        dv: DocumentVersion | None = None
        if document_version_id:
            dv = session.get(DocumentVersion, document_version_id)
        elif document_id:
            doc: Document | None = session.get(Document, document_id)
            if doc and doc.current_version_id:
                dv = session.get(DocumentVersion, doc.current_version_id)
        if dv:
            doc_text = dv.text_extract or ""

    return ContextPack(
        case_id=case.id,
        case_name=case.name,
        lock_mode=case.lock_mode,
        memo_json=case.memo_json or {},
        evidence_summary=evidence_summary,
        document_text=doc_text,
        extra={},
    )
