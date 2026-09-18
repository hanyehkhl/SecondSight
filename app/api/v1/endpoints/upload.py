from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.models.file import MedicalFile
from app.modules.audit import service as audit
from app.modules.file.schemas import FileRead
from app.modules.file.service import FileService, FileValidationError

router = APIRouter(prefix="/files", tags=["files"])


async def _get_owned(service: FileService, file_id: str, user) -> MedicalFile:
    record = await service.get_for_user(file_id, user)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return record


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile, user: CurrentUser, db: DbSession, request: Request) -> FileRead:
    """Upload an image (PNG/JPEG/TIFF/…), a DICOM file, or an audio recording of the question."""
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds {limit // (1024 * 1024)} MB")
    try:
        record = await FileService(db).upload(user, data, file.filename, file.content_type)
    except FileValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await audit.record(
        db,
        action="file.upload",
        resource_type="file",
        resource_id=record.id,
        actor_id=user.id,
        request=request,
        details={"kind": record.kind.value, "size_bytes": record.size_bytes},
    )
    return FileRead.model_validate(record)


@router.get("/{file_id}", response_model=FileRead)
async def get_file(file_id: str, user: CurrentUser, db: DbSession) -> FileRead:
    return FileRead.model_validate(await _get_owned(FileService(db), file_id, user))


@router.get("/{file_id}/preview", response_class=Response, responses={200: {"content": {"image/png": {}}}})
async def get_preview(file_id: str, user: CurrentUser, db: DbSession, request: Request) -> Response:
    """PNG rendition of an image or DICOM file (the exact pixels sent to the model)."""
    service = FileService(db)
    record = await _get_owned(service, file_id, user)
    if record.preview_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File has no image preview")
    content = await service.read_preview(record)
    await audit.record(
        db, action="file.view", resource_type="file", resource_id=record.id, actor_id=user.id, request=request
    )
    return Response(content=content, media_type="image/png", headers={"Cache-Control": "private, no-store"})
