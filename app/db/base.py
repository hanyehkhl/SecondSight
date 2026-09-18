import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt, encrypt


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class EncryptedJSON(TypeDecorator):
    """JSON value stored as a Fernet-encrypted blob (clinical content is encrypted at rest)."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> bytes | None:
        if value is None:
            return None
        return encrypt(json.dumps(value, ensure_ascii=False).encode())

    def process_result_value(self, value: bytes | None, dialect) -> Any:
        if value is None:
            return None
        return json.loads(decrypt(value))


class EncryptedText(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> bytes | None:
        return None if value is None else encrypt(value.encode())

    def process_result_value(self, value: bytes | None, dialect) -> str | None:
        return None if value is None else decrypt(value).decode()


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
