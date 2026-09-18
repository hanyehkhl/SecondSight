import json
import logging
from datetime import UTC, datetime

from app.core.config import get_settings
from app.modules.report import templates
from app.modules.report.schemas import ConfidenceLevel, Language, Report, ReportFinding
from app.modules.vision import prompts
from app.modules.vision.schemas import VisionAnalysis
from app.modules.vision.service import VisionError, VisionService

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE = 0.8


def confidence_level(value: float | None, threshold: float) -> ConfidenceLevel:
    if value is None:
        return "unknown"
    if value >= max(HIGH_CONFIDENCE, threshold):
        return "high"
    if value >= threshold:
        return "moderate"
    return "low"


def evaluate_review(analysis: VisionAnalysis | None, threshold: float) -> list[str]:
    """Return review reason codes; an empty list means the result can be released without escalation."""
    if analysis is None:
        return ["model_unavailable"]
    reasons: list[str] = []
    if analysis.overall_confidence < threshold:
        reasons.append("low_overall_confidence")
    if any(f.severity == "severe" and f.confidence < threshold for f in analysis.findings):
        reasons.append("low_confidence_severe_finding")
    if not analysis.answer_to_question.strip():
        reasons.append("no_answer")
    return reasons


class ReportService:
    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = get_settings().min_confidence_threshold if threshold is None else threshold

    def build(
        self,
        *,
        analysis_id: str,
        analysis: VisionAnalysis | None,
        question: str | None,
        modality: str,
        language: Language,
        review_reason_codes: list[str],
        model: str | None,
    ) -> Report:
        labels = templates.LABELS[language]
        findings = [
            ReportFinding(**f.model_dump(), confidence_level=confidence_level(f.confidence, self.threshold))
            for f in (analysis.findings if analysis else [])
        ]
        overall = analysis.overall_confidence if analysis else None
        report = Report(
            analysis_id=analysis_id,
            language=language,
            title=labels["title"],
            modality=modality,
            question=question,
            summary=analysis.summary if analysis else None,
            answer_to_question=analysis.answer_to_question if analysis else None,
            findings=findings,
            recommendations=analysis.recommendations if analysis else [],
            limitations=analysis.limitations if analysis else None,
            overall_confidence=overall,
            confidence_level=confidence_level(overall, self.threshold),
            needs_human_review=bool(review_reason_codes),
            review_reasons=[templates.REVIEW_REASONS[language].get(c, c) for c in review_reason_codes],
            review_reason_codes=review_reason_codes,
            disclaimer=labels["disclaimer"],
            text="",
            generated_by="template",
            model=model,
            generated_at=datetime.now(UTC),
        )
        report.text = render_text(report)
        return report

    async def build_with_llm(self, llm: VisionService, **kwargs) -> Report:
        """Template report whose `text` is rewritten by the LLM. Falls back to the template text on failure."""
        report = self.build(**kwargs)
        analysis: VisionAnalysis | None = kwargs["analysis"]
        if analysis is None:
            return report
        prompt = prompts.render_prompt(
            prompts.REPORT_GENERATION,
            language_name=templates.LANGUAGE_NAMES[report.language],
            needs_human_review="yes" if report.needs_human_review else "no",
            review_reasons="; ".join(report.review_reasons) or "none",
            analysis_json=json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2),
        )
        try:
            text = (await llm.generate_text(prompt)).strip()
        except VisionError as exc:
            logger.warning("LLM report generation failed, using template: %s", exc)
            return report
        if not text:
            return report
        # The disclaimer is always appended verbatim; it must never depend on model output.
        report.text = f"{text}\n\n{report.disclaimer}"
        report.generated_by = "llm"
        return report


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{round(value * 100)}%"


def render_text(report: Report) -> str:
    lang = report.language
    labels = templates.LABELS[lang]
    severity = templates.SEVERITY[lang]
    level = templates.CONFIDENCE_LEVEL[lang]
    lines: list[str] = [f"# {report.title}", ""]

    if report.needs_human_review:
        lines.append(f"**{labels['review_banner']}**")
        lines.extend(f"- {reason}" for reason in report.review_reasons)
        lines.append("")

    lines.append(f"**{labels['modality']}:** {report.modality}")
    if report.question:
        lines.append(f"**{labels['question']}:** {report.question}")
    lines.append(
        f"**{labels['overall_confidence']}:** {_pct(report.overall_confidence)} ({level[report.confidence_level]})"
    )
    lines.append("")

    if report.summary is None:
        lines.extend([labels["no_analysis"], "", f"_{report.disclaimer}_"])
        return "\n".join(lines)

    lines.extend([f"## {labels['answer']}", report.answer_to_question or "-", ""])
    lines.extend([f"## {labels['summary']}", report.summary, ""])

    lines.append(f"## {labels['findings']}")
    if not report.findings:
        lines.append(labels["no_findings"])
    for index, finding in enumerate(report.findings, start=1):
        lines.append(f"{index}. **{finding.location}**: {finding.description}")
        details = [f"{labels['confidence']}: {_pct(finding.confidence)} ({level[finding.confidence_level]})"]
        if finding.severity:
            details.insert(0, f"{labels['severity']}: {severity[finding.severity]}")
        lines.append(f"   - {' | '.join(details)}")
        if finding.differential:
            lines.append(f"   - {labels['differential']}: {', '.join(finding.differential)}")
    lines.append("")

    if report.recommendations:
        lines.append(f"## {labels['recommendations']}")
        lines.extend(f"- {item}" for item in report.recommendations)
        lines.append("")
    if report.limitations:
        lines.extend([f"## {labels['limitations']}", report.limitations, ""])

    lines.append(f"_{report.disclaimer}_")
    return "\n".join(lines)
