"""Analysis pipeline: audio -> MedASR -> question; image + question -> MedGemma -> structured report.

`run_analysis` is self-contained (it opens its own DB session) so it can run in-process
or inside a Celery worker without changes.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models.analysis import Analysis, AnalysisStatus
from app.models.file import FileKind, MedicalFile
from app.models.user import User
from app.modules.analysis.schemas import AnalysisCreate
from app.modules.audit import service as audit
from app.modules.file.storage import get_storage
from app.modules.notification.service import notify_analysis_finished
from app.modules.report.service import ReportService, evaluate_review
from app.modules.speech.service import SpeechError, get_speech_service
from app.modules.vision.schemas import VisionAnalysis, VisionRequest
from app.modules.vision.service import VisionError, get_vision_service

logger = logging.getLogger(__name__)


class AnalysisInputError(ValueError):
    pass


async def create_analysis(db: AsyncSession, owner: User, data: AnalysisCreate) -> Analysis:
    image = await db.get(MedicalFile, data.image_file_id)
    if image is None or not owner.can_access(image.owner_id):
        raise AnalysisInputError("Image file not found")
    if image.kind not in (FileKind.image, FileKind.dicom):
        raise AnalysisInputError("image_file_id must reference an image or DICOM file")
    if data.audio_file_id:
        audio = await db.get(MedicalFile, data.audio_file_id)
        if audio is None or not owner.can_access(audio.owner_id):
            raise AnalysisInputError("Audio file not found")
        if audio.kind != FileKind.audio:
            raise AnalysisInputError("audio_file_id must reference an audio file")

    modality = (data.modality or image.modality or "").strip()
    if not modality:
        raise AnalysisInputError("modality is required for non-DICOM images")

    analysis = Analysis(
        owner_id=owner.id,
        image_file_id=image.id,
        audio_file_id=data.audio_file_id,
        question=data.question.strip() if data.question else None,
        modality=modality,
        clinical_context=data.clinical_context,
        language=data.language or get_settings().default_report_language,
        status=AnalysisStatus.pending,
        review_reasons=[],
        model_info={},
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    return analysis


def _combine_question(typed: str | None, spoken: str | None) -> str:
    parts = [p.strip() for p in (typed, spoken) if p and p.strip()]
    return "\n".join(parts)


async def run_analysis(analysis_id: str) -> None:
    settings = get_settings()
    storage = get_storage()

    async with get_sessionmaker()() as db:
        analysis = await db.get(Analysis, analysis_id)
        if analysis is None:
            logger.error("Analysis %s not found", analysis_id)
            return
        if analysis.status != AnalysisStatus.pending:
            logger.info("Analysis %s already %s; skipping", analysis_id, analysis.status.value)
            return

        analysis.status = AnalysisStatus.processing
        await db.commit()

        model_info: dict = {}
        try:
            # 1. Speech -> text
            if analysis.audio_file_id:
                audio = await db.get(MedicalFile, analysis.audio_file_id)
                transcription = await get_speech_service().transcribe(
                    await storage.get(audio.storage_key), audio.content_type
                )
                analysis.transcribed_question = transcription.text
                model_info["speech"] = transcription.model

            question = _combine_question(analysis.question, analysis.transcribed_question)
            if not question:
                raise AnalysisInputError("The audio question could not be transcribed into text")

            # 2. Image + question -> structured analysis. Model failure is not fatal: it escalates to a human.
            image = await db.get(MedicalFile, analysis.image_file_id)
            vision = get_vision_service()
            result: VisionAnalysis | None = None
            try:
                vision_result = await vision.analyze(
                    VisionRequest(
                        image_png=await storage.get(image.preview_key),
                        question=question,
                        modality=analysis.modality,
                        clinical_context=analysis.clinical_context,
                    )
                )
                result = vision_result.analysis
                model_info["vision"] = vision_result.model
                model_info["vision_attempts"] = vision_result.attempts
            except VisionError as exc:
                logger.warning("Vision analysis failed for %s: %s", analysis_id, exc)
                analysis.error = str(exc)

            # 3. Confidence gate + report
            reasons = evaluate_review(result, settings.min_confidence_threshold)
            report_service = ReportService(settings.min_confidence_threshold)
            report_kwargs = dict(
                analysis_id=analysis.id,
                analysis=result,
                question=question,
                modality=analysis.modality,
                language=analysis.language,
                review_reason_codes=reasons,
                model=model_info.get("vision"),
            )
            if settings.report_llm_enabled:
                report = await report_service.build_with_llm(vision, **report_kwargs)
            else:
                report = report_service.build(**report_kwargs)

            analysis.result = result.model_dump() if result else None
            analysis.report = report.model_dump(mode="json")
            analysis.overall_confidence = result.overall_confidence if result else None
            analysis.review_reasons = reasons
            analysis.needs_human_review = bool(reasons)
            analysis.status = AnalysisStatus.needs_review if reasons else AnalysisStatus.completed
        except (SpeechError, AnalysisInputError) as exc:
            analysis.status = AnalysisStatus.failed
            analysis.needs_human_review = True
            analysis.error = str(exc)
        except Exception:
            logger.exception("Analysis %s crashed", analysis_id)
            await db.rollback()
            await db.refresh(analysis)
            analysis.status = AnalysisStatus.failed
            analysis.needs_human_review = True
            analysis.error = "Internal error during analysis"

        analysis.model_info = model_info
        analysis.completed_at = datetime.now(UTC)
        await audit.record(
            db,
            action="analysis.finished",
            resource_type="analysis",
            resource_id=analysis.id,
            details={"status": analysis.status.value, "review_reasons": analysis.review_reasons, **model_info},
            commit=False,
        )
        await db.commit()
        await notify_analysis_finished(analysis)
