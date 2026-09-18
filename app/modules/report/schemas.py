from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.vision.schemas import Finding

Language = Literal["fa", "en"]
ConfidenceLevel = Literal["high", "moderate", "low", "unknown"]


class ReportFinding(Finding):
    confidence_level: ConfidenceLevel


class Report(BaseModel):
    analysis_id: str
    language: Language
    title: str
    modality: str
    question: str | None
    summary: str | None
    answer_to_question: str | None
    findings: list[ReportFinding]
    recommendations: list[str]
    limitations: str | None
    overall_confidence: float | None
    confidence_level: ConfidenceLevel
    needs_human_review: bool
    review_reasons: list[str]  # localized, human-readable
    review_reason_codes: list[str]
    disclaimer: str
    text: str  # full rendered report, ready to display or export
    generated_by: Literal["template", "llm"]
    model: str | None
    generated_at: datetime
