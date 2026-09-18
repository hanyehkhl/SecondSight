from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.api.deps import CurrentUser, DbSession
from app.api.v1.endpoints.analysis import get_owned_analysis
from app.core.config import get_settings
from app.models.analysis import AnalysisStatus
from app.modules.audit import service as audit
from app.modules.report.schemas import Language, Report
from app.modules.report.service import ReportService
from app.modules.vision.schemas import VisionAnalysis

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{analysis_id}", response_model=Report, responses={200: {"content": {"text/markdown": {}}}})
async def get_report(
    analysis_id: str,
    user: CurrentUser,
    db: DbSession,
    request: Request,
    language: Language | None = None,
    format: Literal["json", "text"] = "json",
):
    """The structured report. Pass `language` to re-render in another language, `format=text` for Markdown."""
    analysis = await get_owned_analysis(db, analysis_id, user)
    if analysis.status in (AnalysisStatus.pending, AnalysisStatus.processing):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Analysis is still {analysis.status.value}")
    if analysis.report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, analysis.error or "No report available")

    report = Report.model_validate(analysis.report)
    if language and language != report.language:
        # Re-rendered from the stored structured result; the model is not called again.
        report = ReportService(get_settings().min_confidence_threshold).build(
            analysis_id=analysis.id,
            analysis=VisionAnalysis.model_validate(analysis.result) if analysis.result else None,
            question=report.question,
            modality=analysis.modality,
            language=language,
            review_reason_codes=analysis.review_reasons,
            model=report.model,
        )

    await audit.record(
        db,
        action="report.view",
        resource_type="analysis",
        resource_id=analysis.id,
        actor_id=user.id,
        request=request,
        details={"language": report.language, "format": format},
    )
    if format == "text":
        return PlainTextResponse(report.text, media_type="text/markdown; charset=utf-8")
    return report
