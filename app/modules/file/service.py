import asyncio
import hashlib
import io
import logging
from pathlib import PurePath

from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import new_id
from app.models.file import FileKind, MedicalFile
from app.models.user import User
from app.modules.file.dicom import DicomError, dicom_to_png, is_dicom
from app.modules.file.storage import StorageBackend, get_storage

logger = logging.getLogger(__name__)

AUDIO_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/flac",
    "audio/ogg",
    "audio/webm",
    "audio/mp4",
    "audio/x-m4a",
}
IMAGE_FORMATS = {"PNG", "JPEG", "TIFF", "BMP", "WEBP"}


class FileValidationError(ValueError):
    pass


def _safe_filename(name: str | None) -> str:
    # Only the base name is kept; it is metadata and never used as a storage path.
    return PurePath(name or "upload").name[:255] or "upload"


def _image_to_png(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in IMAGE_FORMATS:
                raise FileValidationError(f"Unsupported image format: {image.format}")
            image.load()
            # Re-encoding also drops EXIF and other embedded metadata.
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise FileValidationError("File is not a valid image") from exc


class FileService:
    def __init__(self, db: AsyncSession, storage: StorageBackend | None = None) -> None:
        self.db = db
        self.storage = storage or get_storage()

    async def upload(self, owner: User, data: bytes, filename: str | None, content_type: str | None) -> MedicalFile:
        if not data:
            raise FileValidationError("Empty file")
        content_type = (content_type or "application/octet-stream").split(";")[0].strip().lower()

        file_id = new_id()
        record = MedicalFile(
            id=file_id,
            owner_id=owner.id,
            original_filename=_safe_filename(filename),
            content_type=content_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            storage_key=f"{owner.id}/{file_id}/original",
            file_metadata={},
        )
        preview: bytes | None = None

        if is_dicom(data) or content_type == "application/dicom":
            record.kind = FileKind.dicom
            try:
                preview, metadata = await asyncio.to_thread(dicom_to_png, data)
            except DicomError as exc:
                raise FileValidationError(str(exc)) from exc
            record.file_metadata = metadata
            record.modality = metadata.get("Modality")
        elif content_type in AUDIO_CONTENT_TYPES:
            record.kind = FileKind.audio
        else:
            record.kind = FileKind.image
            preview = await asyncio.to_thread(_image_to_png, data)

        # Bytes are written before the row, so a committed record always points at stored data.
        await self.storage.put(record.storage_key, data)
        if preview is not None:
            record.preview_key = f"{owner.id}/{file_id}/preview.png"
            await self.storage.put(record.preview_key, preview)

        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        logger.info("Stored file %s (%s, %d bytes)", record.id, record.kind.value, record.size_bytes)
        return record

    async def get_for_user(self, file_id: str, user: User) -> MedicalFile | None:
        record = await self.db.get(MedicalFile, file_id)
        if record is None or not user.can_access(record.owner_id):
            return None
        return record

    async def read_original(self, record: MedicalFile) -> bytes:
        return await self.storage.get(record.storage_key)

    async def read_preview(self, record: MedicalFile) -> bytes:
        if record.preview_key is None:
            raise FileValidationError("File has no image preview")
        return await self.storage.get(record.preview_key)
