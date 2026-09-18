import enum
from typing import Any

from sqlalchemy import JSON, BigInteger, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class FileKind(enum.StrEnum):
    image = "image"
    dicom = "dicom"
    audio = "audio"


class MedicalFile(IdMixin, TimestampMixin, Base):
    __tablename__ = "files"

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[FileKind] = mapped_column(Enum(FileKind, native_enum=False, length=20))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255))
    # PNG rendition used for model input and display (images and DICOM only).
    preview_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modality: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Non-identifying technical metadata only (PHI is never copied here).
    file_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    @property
    def has_preview(self) -> bool:
        return self.preview_key is not None
