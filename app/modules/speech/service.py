"""Speech-to-text behind a single interface. Swap the backend via SPEECH_BACKEND."""

import asyncio
import io
import logging
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.modules.speech.schemas import Transcription

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000


class SpeechError(RuntimeError):
    pass


class SpeechService(Protocol):
    async def transcribe(self, audio: bytes, content_type: str) -> Transcription: ...


class MockSpeechService:
    """Deterministic backend for development and tests; no model required."""

    async def transcribe(self, audio: bytes, content_type: str) -> Transcription:
        return Transcription(
            text="Is there any evidence of pneumonia or pleural effusion?",
            model="mock-asr",
            language="en",
        )


class MedASRLocalService:
    """Runs google/medasr in-process via Hugging Face transformers (install requirements-ml.txt)."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._pipeline = None
        self._lock = asyncio.Lock()

    async def _load(self):
        async with self._lock:
            if self._pipeline is None:
                from transformers import pipeline

                logger.info("Loading ASR model %s", self.model_id)
                self._pipeline = await asyncio.to_thread(pipeline, "automatic-speech-recognition", model=self.model_id)
        return self._pipeline

    async def transcribe(self, audio: bytes, content_type: str) -> Transcription:
        asr = await self._load()

        def _run() -> str:
            import librosa

            waveform, _ = librosa.load(io.BytesIO(audio), sr=SAMPLE_RATE, mono=True)
            output = asr({"raw": waveform, "sampling_rate": SAMPLE_RATE}, chunk_length_s=20)
            return output["text"]

        try:
            text = await asyncio.to_thread(_run)
        except Exception as exc:
            raise SpeechError(f"Transcription failed: {exc}") from exc
        return Transcription(text=text.strip(), model=self.model_id)


class MedASRHttpService:
    """Calls a remote MedASR deployment. Expects `POST <url>` (multipart `file`) -> {"text": "..."}."""

    def __init__(self, endpoint_url: str, api_key: str | None, model_id: str) -> None:
        self.endpoint_url = endpoint_url
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model_id = model_id

    async def transcribe(self, audio: bytes, content_type: str) -> Transcription:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    self.endpoint_url,
                    headers=self.headers,
                    files={"file": ("audio", audio, content_type)},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SpeechError(f"MedASR endpoint error: {exc}") from exc
        text = payload.get("text")
        if not isinstance(text, str):
            raise SpeechError("MedASR endpoint returned no text")
        return Transcription(text=text.strip(), model=self.model_id, language=payload.get("language"))


@lru_cache
def get_speech_service() -> SpeechService:
    settings = get_settings()
    if settings.speech_backend == "medasr_local":
        return MedASRLocalService(settings.medasr_model_id)
    if settings.speech_backend == "medasr_http":
        if not settings.medasr_endpoint_url:
            raise RuntimeError("MEDASR_ENDPOINT_URL is required for the medasr_http backend")
        api_key = settings.medasr_api_key.get_secret_value() if settings.medasr_api_key else None
        return MedASRHttpService(settings.medasr_endpoint_url, api_key, settings.medasr_model_id)
    return MockSpeechService()
