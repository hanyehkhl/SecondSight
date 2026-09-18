from app.modules.report.service import ReportService, confidence_level, evaluate_review
from app.modules.vision.schemas import VisionAnalysis


def _analysis(overall: float, severe_conf: float | None = None, answer: str = "Yes.") -> VisionAnalysis:
    findings = [{"location": "lung", "description": "opacity", "severity": "mild", "confidence": 0.9}]
    if severe_conf is not None:
        findings.append(
            {"location": "heart", "description": "enlarged", "severity": "severe", "confidence": severe_conf}
        )
    return VisionAnalysis(summary="s", findings=findings, answer_to_question=answer, overall_confidence=overall)


def test_evaluate_review():
    assert evaluate_review(_analysis(0.9), 0.6) == []
    assert evaluate_review(_analysis(0.5), 0.6) == ["low_overall_confidence"]
    assert evaluate_review(_analysis(0.9, severe_conf=0.3), 0.6) == ["low_confidence_severe_finding"]
    assert evaluate_review(_analysis(0.9, answer="  "), 0.6) == ["no_answer"]
    assert evaluate_review(None, 0.6) == ["model_unavailable"]


def test_confidence_levels():
    assert confidence_level(0.95, 0.6) == "high"
    assert confidence_level(0.7, 0.6) == "moderate"
    assert confidence_level(0.2, 0.6) == "low"
    assert confidence_level(None, 0.6) == "unknown"


def test_report_rendering_in_both_languages():
    service = ReportService(0.6)
    kwargs = dict(
        analysis_id="a1",
        analysis=_analysis(0.5),
        question="Q?",
        modality="Chest CT",
        review_reason_codes=["low_overall_confidence"],
        model="m",
    )
    en = service.build(language="en", **kwargs)
    assert en.needs_human_review
    assert "HUMAN REVIEW REQUIRED" in en.text
    assert "50%" in en.text

    fa = service.build(language="fa", **kwargs)
    assert fa.title == "گزارش نظر دوم هوش مصنوعی"
    assert "نیاز به بررسی انسانی" in fa.text
    assert fa.findings[0].severity == "mild"  # structured data stays canonical; only text is localized
    assert "خفیف" in fa.text


def test_report_without_analysis():
    report = ReportService(0.6).build(
        analysis_id="a1",
        analysis=None,
        question="Q?",
        modality="MRI",
        language="en",
        review_reason_codes=["model_unavailable"],
        model=None,
    )
    assert report.confidence_level == "unknown"
    assert "No automated analysis" in report.text
