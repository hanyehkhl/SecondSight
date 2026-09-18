import pytest

from app.modules.vision.prompts import build_analysis_prompt
from app.modules.vision.service import VisionParseError, parse_analysis

VALID = """{
  "summary": "Normal study.",
  "findings": [{"location": "lungs", "description": "clear", "severity": "null", "confidence": 92, "differential": []}],
  "answer_to_question": "No.",
  "recommendations": [],
  "limitations": ["single view", "low resolution"],
  "overall_confidence": "0.9"
}"""


def test_parses_fenced_json_with_chatter():
    analysis = parse_analysis(f"Sure! Here is the analysis:\n```json\n{VALID}\n```\nHope this helps.")
    assert analysis.summary == "Normal study."
    finding = analysis.findings[0]
    assert finding.severity is None  # "null" string normalized
    assert finding.confidence == pytest.approx(0.92)  # percentage normalized
    assert analysis.overall_confidence == pytest.approx(0.9)
    assert analysis.limitations == "single view; low resolution"


def test_confidence_is_clamped():
    analysis = parse_analysis(VALID.replace('"0.9"', "7000"))
    assert analysis.overall_confidence == 1.0


@pytest.mark.parametrize(
    "text",
    [
        "no json here",
        "{ broken json",
        "[1, 2, 3]",
        '{"summary": "missing required fields"}',
    ],
)
def test_invalid_output_raises(text):
    with pytest.raises(VisionParseError):
        parse_analysis(text)


def test_prompt_rendering_keeps_json_braces():
    prompt = build_analysis_prompt("Is there a fracture?", "Wrist X-ray", None)
    assert "Is there a fracture?" in prompt
    assert "Wrist X-ray" in prompt
    assert "None provided" in prompt
    assert '"overall_confidence"' in prompt
    assert "{transcribed_question}" not in prompt
