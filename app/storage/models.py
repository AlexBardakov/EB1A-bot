# app/storage/models.py
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    Integer,
    Enum,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# -------------------- Enums --------------------

class DocumentStatus(str, enum.Enum):
    draft = "draft"
    reviewed = "reviewed"
    approved = "approved"
    filed = "filed"
    rfe_response = "rfe_response"
    final = "final"


class EvidenceStatus(str, enum.Enum):
    draft = "draft"
    verified = "verified"
    archived = "archived"


class RunMode(str, enum.Enum):
    review = "review"
    requirements = "requirements"
    fees = "fees"
    filing = "filing"
    premium = "premium"
    criteria_map = "criteria_map"
    strengthen = "strengthen"
    wording = "wording"
    rfe_drill = "rfe_drill"
    general = "general"


# -------------------- Core tables --------------------

class ChatState(Base):
    """
    Tracks per-chat active case and basic preferences.
    """
    __tablename__ = "chat_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active_case_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cases.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    active_case: Mapped[Optional["Case"]] = relationship("Case")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    # "Canonical memo" stored as JSON so you can keep EN/RU, pillars, criteria, etc.
    memo_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    lock_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    evidence_items: Mapped[List["EvidenceItem"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    documents: Mapped[List["Document"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    tasks: Mapped[List["Task"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    checkpoints: Mapped[List["Checkpoint"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        UniqueConstraint("case_id", "exhibit_code", name="uq_case_exhibit"),
        Index("ix_evidence_case_criterion", "case_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)

    exhibit_code: Mapped[str] = mapped_column(String(32))  # e.g., "B-5"
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Tags like ["awards", "judging", "critical_role", "high_salary"]
    criterion_tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    strength: Mapped[int] = mapped_column(Integer, default=3, nullable=False)  # 1..5
    status: Mapped[EvidenceStatus] = mapped_column(Enum(EvidenceStatus), default=EvidenceStatus.draft, nullable=False)

    # File references stored as list of FileObject ids
    file_ids: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    case: Mapped["Case"] = relationship(back_populates="evidence_items")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("case_id", "title", name="uq_case_doc_title"),
        Index("ix_doc_case_status", "case_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)

    doc_type: Mapped[str] = mapped_column(String(64))  # petition, support_letter, resume, exhibit_index, ...
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.draft, nullable=False)

    current_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("document_versions.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    case: Mapped["Case"] = relationship(back_populates="documents")
    versions: Mapped[List["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentVersion.document_id",
    )
    current_version: Mapped[Optional["DocumentVersion"]] = relationship(
        foreign_keys=[current_version_id],
        post_update=True,
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        Index("ix_docver_doc_created", "document_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)

    # Where the raw file lives (MinIO/S3) or local path.
    storage_url: Mapped[str] = mapped_column(String(500))

    # Plain text extracted for LLM work (store it here to avoid re-OCR/re-parse)
    text_extract: Mapped[str] = mapped_column(Text, default="", nullable=False)

    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), default="system", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="versions")


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    __table_args__ = (
        Index("ix_checkpoint_case_created", "case_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    label: Mapped[str] = mapped_column(String(240))
    snapshot_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    case: Mapped["Case"] = relationship(back_populates="checkpoints")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_task_case_status", "case_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)

    title: Mapped[str] = mapped_column(String(240))
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)  # 1..5
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)

    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    linked_evidence_ids: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    case: Mapped["Case"] = relationship(back_populates="tasks")


class Run(Base):
    """
    Stores every LLM 'run' (for auditability and debugging).
    """
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_run_case_created", "case_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)

    mode: Mapped[RunMode] = mapped_column(Enum(RunMode), default=RunMode.general, nullable=False)

    inputs_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Raw text for transparency (you can also store JSON)
    prompt_pack: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    model_a_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model_b_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    critique_a: Mapped[str] = mapped_column(Text, default="", nullable=False)
    critique_b: Mapped[str] = mapped_column(Text, default="", nullable=False)
    judge_output: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    case: Mapped["Case"] = relationship()
