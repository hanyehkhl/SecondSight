"""Prompt templates live in the top-level prompts/ directory so they can be edited without code changes.

Placeholders use {name} syntax, but rendering is a plain substitution of known keys only,
so the literal JSON braces in the templates are left untouched.
"""

from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

SYSTEM = "medgemma_system"
ANALYSIS = "medgemma_analysis"
JSON_REPAIR = "medgemma_json_repair"
REPORT_GENERATION = "report_generation"


@lru_cache
def load_prompt(name: str) -> str:
    path: Path = get_settings().prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8").strip()


def render_prompt(name: str, **values: object) -> str:
    text = load_prompt(name)
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def build_analysis_prompt(question: str, modality: str, clinical_context: str | None) -> str:
    return render_prompt(
        ANALYSIS,
        transcribed_question=question.strip(),
        modality=modality.strip(),
        clinical_context=(clinical_context or "").strip() or "None provided",
    )
