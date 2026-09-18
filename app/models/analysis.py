import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, EncryptedJSON, EncryptedText, IdMixin, TimestampMixin


class AnalysisStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    needs_review = "needs_review"  # model answered with low confidence or not at all
    failed = "failed"  # internal error (e.g. missing file); not a clinical outcome


class Analysis(IdMixin, TimestampMixin, Base):
    __tablename__ = "analyses"

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    image_file_id: Mapped[str] = mapped_column(ForeignKey("files.id"))
    audio_file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"), nullable=True)

    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus, native_enum=False, length=20), default=AnalysisStatus.pending, index=True
    )
    modality: Mapped[str] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(5))

    # Clinical content: encrypted at rest.
    question: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    transcribed_question: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    clinical_context: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON, nullable=True)
    report: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON, nullable=True)

    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
