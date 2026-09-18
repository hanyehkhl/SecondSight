from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.analysis import AnalysisStatus
from app.modules.report.schemas import Language
from app.modules.vision.schemas import VisionAnalysis


class AnalysisCreate(BaseModel):
    image_file_id: str
    audio_file_id: str | None = None
    question: str | None = Field(default=None, max_length=4000)
    modality: str | None = Field(
        default=None, max_length=100, description="e.g. 'Chest X-ray', 'Brain MRI'. Defaults to the DICOM modality."
    )
    clinical_context: str | None = Field(default=None, max_length=4000)
    language: Language | None = None

    @model_validator(mode="after")
    def _needs_question(self) -> "AnalysisCreate":
        if not (self.question and self.question.strip()) and not self.audio_file_id:
            raise ValueError("Provide a text question, an audio question (audio_file_id), or both")
        return self


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: AnalysisStatus
    image_file_id: str
    audio_file_id: str | None
    modality: str
    language: str
    question: str | None
    transcribed_question: str | None
    result: VisionAnalysis | None
    overall_confidence: float | None
    needs_human_review: bool
    review_reasons: list[str]
    model_info: dict
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: AnalysisStatus
    modality: str
    overall_confidence: float | None
    needs_human_review: bool
    created_at: datetime
    completed_at: datetime | None
