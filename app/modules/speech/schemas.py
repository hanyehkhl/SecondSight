from pydantic import BaseModel


class Transcription(BaseModel):
    text: str
    model: str
    language: str | None = None
