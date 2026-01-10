# app/rag/models.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import (
    Integer, String, Text, DateTime, JSON, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.models import Base

# pgvector SQLAlchemy type
# Убедитесь, что установлен пакет: pip install pgvector
from pgvector.sqlalchemy import Vector


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint("source_url", "chunk_id", name="uq_rag_source_chunk"),
        Index("ix_rag_kind", "kind"),
        Index("ix_rag_updated", "source_last_updated"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # What is this chunk about? (policy_manual, cfr, form_i140, form_i907, fees, filing, alerts, etc.)
    kind: Mapped[str] = mapped_column(String(64), index=True)

    source_url: Mapped[str] = mapped_column(String(800), index=True)
    source_title: Mapped[str] = mapped_column(String(400), default="", nullable=False)

    # A stable chunk identifier (e.g. "pm-6f2-0003")
    chunk_id: Mapped[str] = mapped_column(String(64), index=True)

    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional metadata: headings, breadcrumbs, section ids, etc.
    meta_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Track source update time if known (parsed or manually set)
    source_last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Embedding vector (dim=1536 for OpenAI text-embedding-3-small)
    embedding: Mapped[list] = mapped_column(Vector(1536))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)