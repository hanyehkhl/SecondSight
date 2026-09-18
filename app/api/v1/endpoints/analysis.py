from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.analysis import Analysis
from app.models.user import User
from app.modules.analysis.schemas import AnalysisCreate, AnalysisRead, AnalysisSummary
from app.modules.analysis.service import AnalysisInputError, create_analysis
from app.modules.analysis.tasks import dispatch_analysis
from app.modules.audit import service as audit

router = APIRouter(prefix="/analyses", tags=["analyses"])


async def get_owned_analysis(db, analysis_id: str, user: User) -> Analysis:
    analysis = await db.get(Analysis, analysis_id)
    if analysis is None or not user.can_access(analysis.owner_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return analysis


@router.post("", response_model=AnalysisRead, status_code=status.HTTP_202_ACCEPTED)
async def start_analysis(
    data: AnalysisCreate, user: CurrentUser, db: DbSession, request: Request, background_tasks: BackgroundTasks
) -> Analysis:
    """Start a second-opinion analysis. Poll `GET /analyses/{id}` until the status is no longer pending/processing."""
    try:
        analysis = await create_analysis(db, user, data)
    except AnalysisInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await audit.record(
        db,
        action="analysis.create",
        resource_type="analysis",
        resource_id=analysis.id,
        actor_id=user.id,
        request=request,
        details={"image_file_id": analysis.image_file_id, "audio_file_id": analysis.audio_file_id},
    )
    dispatch_analysis(analysis.id, background_tasks)
    return analysis


@router.get("", response_model=list[AnalysisSummary])
async def list_analyses(user: CurrentUser, db: DbSession, limit: int = 50, offset: int = 0) -> list[Analysis]:
    query = (
        select(Analysis)
        .where(Analysis.owner_id == user.id)
        .order_by(Analysis.created_at.desc())
        .limit(min(limit, 200))
        .offset(offset)
    )
    return list(await db.scalars(query))


@router.get("/{analysis_id}", response_model=AnalysisRead)
async def get_analysis(analysis_id: str, user: CurrentUser, db: DbSession, request: Request) -> Analysis:
    analysis = await get_owned_analysis(db, analysis_id, user)
    await audit.record(
        db, action="analysis.view", resource_type="analysis", resource_id=analysis.id, actor_id=user.id, request=request
    )
    return analysis
