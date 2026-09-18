from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.file import FileKind


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: FileKind
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    modality: str | None
    has_preview: bool
    file_metadata: dict[str, Any]
    created_at: datetime
