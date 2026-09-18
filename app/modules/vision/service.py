"""Image analysis behind a single interface. Swap the backend via VISION_BACKEND.

Every backend only implements `_complete` (one chat completion). Prompting, JSON parsing,
validation and repair retries are shared, so all backends behave identically downstream.
"""

import asyncio
import base64
import io
import json
import logging
import re
from functools import lru_cache
from typing import Literal, Protocol

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.modules.vision import prompts
from app.modules.vision.schemas import VisionAnalysis, VisionRequest, VisionResult

logger = logging.getLogger(__name__)

Role = Literal["user", "assistant"]
Turn = tuple[Role, str]


class VisionError(RuntimeError):
    """The model could not produce a usable analysis. Callers fall back to human review."""


class VisionParseError(VisionError):
    pass


class VisionService(Protocol):
    model_name: str

    async def analyze(self, request: VisionRequest) -> VisionResult: ...
    async def generate_text(self, prompt: str) -> str: ...


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_object(text: str) -> dict:
    """Pull the first JSON object out of model output (handles markdown fences and chatter)."""
    fenced = _FENCE.search(text)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start == -1:
        raise VisionParseError("no JSON object found")
    try:
        obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
    except json.JSONDecodeError as exc:
        raise VisionParseError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise VisionParseError("top-level JSON value is not an object")
    return obj


def parse_analysis(text: str) -> VisionAnalysis:
    data = extract_json_object(text)
    try:
        return VisionAnalysis.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in err["loc"]) for err in exc.errors())
        raise VisionParseError(f"schema mismatch in: {fields}") from exc


class BaseVisionService:
    model_name = "base"

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    async def _complete(self, system: str, turns: list[Turn], image_png: bytes | None) -> str:
        raise NotImplementedError

    async def analyze(self, request: VisionRequest) -> VisionResult:
        system = prompts.load_prompt(prompts.SYSTEM)
        turns: list[Turn] = [
            ("user", prompts.build_analysis_prompt(request.question, request.modality, request.clinical_context))
        ]
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 2):
            try:
                raw = await self._complete(system, turns, request.image_png)
            except VisionError as exc:
                last_error = exc
                logger.warning("Vision backend call failed (attempt %d): %s", attempt, exc)
                continue
            try:
                analysis = parse_analysis(raw)
            except VisionParseError as exc:
                last_error = exc
                logger.warning("Unparseable model output (attempt %d): %s", attempt, exc)
                turns = turns[:1] + [
                    ("assistant", raw),
                    ("user", prompts.render_prompt(prompts.JSON_REPAIR, error=str(exc))),
                ]
                continue
            return VisionResult(analysis=analysis, raw_output=raw, model=self.model_name, attempts=attempt)

        raise VisionError(f"No valid analysis after {self.max_retries + 1} attempts: {last_error}")

    async def generate_text(self, prompt: str) -> str:
        return await self._complete(prompts.load_prompt(prompts.SYSTEM), [("user", prompt)], None)


class MockVisionService(BaseVisionService):
    """Deterministic backend for development and tests; returns a plausible chest X-ray read."""

    model_name = "mock-vision"

    async def _complete(self, system: str, turns: list[Turn], image_png: bytes | None) -> str:
        if image_png is None:
            return "Mock report text generated from the structured analysis."
        return json.dumps(
            {
                "summary": "Mild patchy opacity in the right lower zone; no pleural effusion or pneumothorax.",
                "findings": [
                    {
                        "location": "right lower lobe",
                        "description": "Patchy airspace opacity without volume loss.",
                        "severity": "mild",
                        "confidence": 0.78,
                        "differential": ["early pneumonia", "atelectasis"],
                    },
                    {
                        "location": "pleural spaces",
                        "description": "Costophrenic angles are sharp; no effusion.",
                        "severity": None,
                        "confidence": 0.9,
                        "differential": [],
                    },
                ],
                "answer_to_question": (
                    "Findings are compatible with early right lower lobe pneumonia. There is no pleural effusion."
                ),
                "recommendations": [
                    "Correlate with clinical and laboratory findings",
                    "Follow-up radiograph in 4-6 weeks",
                ],
                "limitations": "Single frontal view; lateral view not available.",
                "overall_confidence": 0.8,
            }
        )


class MedGemmaOpenAIService(BaseVisionService):
    """MedGemma served behind an OpenAI-compatible API (e.g. vLLM, TGI, or a Vertex AI endpoint proxy)."""

    def __init__(
        self, base_url: str, model_id: str, api_key: str | None, timeout: float, max_tokens: int, max_retries: int
    ) -> None:
        super().__init__(max_retries)
        self.base_url = base_url.rstrip("/")
        self.model_name = model_id
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = timeout
        self.max_tokens = max_tokens

    async def _complete(self, system: str, turns: list[Turn], image_png: bytes | None) -> str:
        messages: list[dict] = [{"role": "system", "content": system}]
        for index, (role, text) in enumerate(turns):
            if index == 0 and image_png is not None:
                image_url = "data:image/png;base64," + base64.b64encode(image_png).decode()
                content: object = [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]
            else:
                content = text
            messages.append({"role": role, "content": content})

        body = {"model": self.model_name, "messages": messages, "max_tokens": self.max_tokens, "temperature": 0}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/chat/completions", json=body, headers=self.headers)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise VisionError(f"MedGemma endpoint error: {exc}") from exc


class MedGemmaLocalService(BaseVisionService):
    """Runs MedGemma in-process with transformers (install requirements-ml.txt; a GPU is strongly recommended)."""

    def __init__(self, model_id: str, max_tokens: int, max_retries: int) -> None:
        super().__init__(max_retries)
        self.model_name = model_id
        self.max_tokens = max_tokens
        self._model = None
        self._processor = None
        self._load_lock = asyncio.Lock()
        self._gpu_lock = asyncio.Lock()  # one generation at a time per process

    async def _load(self) -> None:
        async with self._load_lock:
            if self._model is not None:
                return

            def _load_sync():
                import torch
                from transformers import AutoModelForImageTextToText, AutoProcessor

                dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
                model = AutoModelForImageTextToText.from_pretrained(
                    self.model_name, torch_dtype=dtype, device_map="auto"
                )
                return model, AutoProcessor.from_pretrained(self.model_name)

            logger.info("Loading vision model %s", self.model_name)
            self._model, self._processor = await asyncio.to_thread(_load_sync)

    async def _complete(self, system: str, turns: list[Turn], image_png: bytes | None) -> str:
        await self._load()
        model, processor = self._model, self._processor

        def _generate() -> str:
            import torch
            from PIL import Image

            messages: list[dict] = [{"role": "system", "content": [{"type": "text", "text": system}]}]
            for index, (role, text) in enumerate(turns):
                content: list[dict] = [{"type": "text", "text": text}]
                if index == 0 and image_png is not None:
                    content.append({"type": "image", "image": Image.open(io.BytesIO(image_png)).convert("RGB")})
                messages.append({"role": role, "content": content})

            inputs = processor.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt"
            ).to(model.device, dtype=model.dtype)
            input_len = inputs["input_ids"].shape[-1]
            with torch.inference_mode():
                output = model.generate(**inputs, max_new_tokens=self.max_tokens, do_sample=False)
            return processor.decode(output[0][input_len:], skip_special_tokens=True)

        async with self._gpu_lock:
            try:
                return await asyncio.to_thread(_generate)
            except Exception as exc:
                raise VisionError(f"MedGemma inference failed: {exc}") from exc


@lru_cache
def get_vision_service() -> VisionService:
    settings = get_settings()
    if settings.vision_backend == "medgemma_local":
        return MedGemmaLocalService(
            settings.medgemma_model_id, settings.medgemma_max_new_tokens, settings.vision_max_retries
        )
    if settings.vision_backend == "medgemma_openai":
        if not settings.medgemma_endpoint_url:
            raise RuntimeError("MEDGEMMA_ENDPOINT_URL is required for the medgemma_openai backend")
        return MedGemmaOpenAIService(
            base_url=settings.medgemma_endpoint_url,
            model_id=settings.medgemma_model_id,
            api_key=settings.medgemma_api_key.get_secret_value() if settings.medgemma_api_key else None,
            timeout=settings.vision_timeout_seconds,
            max_tokens=settings.medgemma_max_new_tokens,
            max_retries=settings.vision_max_retries,
        )
    return MockVisionService(settings.vision_max_retries)
