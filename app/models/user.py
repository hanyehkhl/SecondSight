import enum

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class UserRole(enum.StrEnum):
    physician = "physician"
    patient = "patient"
    clinic = "clinic"
    admin = "admin"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def can_access(self, owner_id: str) -> bool:
        return self.id == owner_id or self.role == UserRole.admin
