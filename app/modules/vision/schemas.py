from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["mild", "moderate", "severe"]


def _normalize_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 1.0 < number <= 100.0:  # model answered as a percentage
        number /= 100.0
    return min(max(number, 0.0), 1.0)


class Finding(BaseModel):
    location: str
    description: str
    severity: Severity | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    differential: list[str] = []

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip().lower()
        return value if value in ("mild", "moderate", "severe") else None

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float:
        return _normalize_confidence(value)


class VisionAnalysis(BaseModel):
    summary: str
    findings: list[Finding] = []
    answer_to_question: str
    recommendations: list[str] = []
    limitations: str | None = None
    overall_confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("overall_confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float:
        return _normalize_confidence(value)

    @field_validator("limitations", mode="before")
    @classmethod
    def _limitations(cls, value: Any) -> str | None:
        if isinstance(value, list):
            return "; ".join(str(v) for v in value)
        return value


@dataclass(frozen=True)
class VisionRequest:
    image_png: bytes
    question: str
    modality: str
    clinical_context: str | None = None


@dataclass(frozen=True)
class VisionResult:
    analysis: VisionAnalysis
    raw_output: str
    model: str
    attempts: int
