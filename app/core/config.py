import base64
import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_JWT_SECRET = "insecure-development-secret-change-me-in-production"

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SecondSight"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = []

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/secondsight.db"

    # Auth
    jwt_secret: SecretStr = SecretStr(_DEFAULT_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Storage (files are always encrypted at rest)
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: Path = BASE_DIR / "data" / "storage"
    storage_encryption_key: SecretStr | None = None  # Fernet key (urlsafe base64, 32 bytes)
    s3_endpoint_url: str | None = None  # e.g. http://minio:9000
    s3_bucket: str = "secondsight"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str = "us-east-1"
    max_upload_mb: int = 100

    # Speech (MedASR)
    speech_backend: Literal["mock", "medasr_local", "medasr_http"] = "mock"
    medasr_model_id: str = "google/medasr"
    medasr_endpoint_url: str | None = None
    medasr_api_key: SecretStr | None = None

    # Vision (MedGemma)
    vision_backend: Literal["mock", "medgemma_local", "medgemma_openai"] = "mock"
    medgemma_model_id: str = "google/medgemma-1.5-4b-it"
    medgemma_endpoint_url: str | None = None  # OpenAI-compatible base URL, e.g. http://vllm:8000/v1
    medgemma_api_key: SecretStr | None = None
    medgemma_max_new_tokens: int = 2048
    vision_timeout_seconds: float = 180.0
    vision_max_retries: int = 2

    # Report
    prompts_dir: Path = BASE_DIR / "prompts"
    min_confidence_threshold: float = 0.6
    default_report_language: Literal["fa", "en"] = "en"
    report_llm_enabled: bool = False

    # Background work
    task_backend: Literal["inline", "celery"] = "inline"
    redis_url: str = "redis://localhost:6379/0"

    # Notification
    notification_webhook_url: str | None = None

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if self.environment == "production":
            secret = self.jwt_secret.get_secret_value()
            if secret == _DEFAULT_JWT_SECRET or len(secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters in production")
            if self.storage_encryption_key is None:
                raise ValueError("STORAGE_ENCRYPTION_KEY must be set in production")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def fernet_key(self) -> bytes:
        if self.storage_encryption_key is not None:
            return self.storage_encryption_key.get_secret_value().encode()
        # Development only: derive a stable key from the JWT secret so data survives restarts.
        logger.warning("STORAGE_ENCRYPTION_KEY not set; deriving a development key from JWT_SECRET")
        digest = hashlib.sha256(b"secondsight-storage:" + self.jwt_secret.get_secret_value().encode()).digest()
        return base64.urlsafe_b64encode(digest)


@lru_cache
def get_settings() -> Settings:
    return Settings()
