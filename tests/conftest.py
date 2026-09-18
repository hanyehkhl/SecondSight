import io
import os
import tempfile
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

# Configure before any app module is imported (settings are cached on first use).
_TMP = Path(tempfile.mkdtemp(prefix="secondsight-test-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "WARNING",
        "JWT_SECRET": "test-secret-that-is-at-least-32-bytes-long",
        "STORAGE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_PATH": str(_TMP / "storage"),
        "SPEECH_BACKEND": "mock",
        "VISION_BACKEND": "mock",
        "TASK_BACKEND": "inline",
        "REPORT_LLM_ENABLED": "false",
        "MIN_CONFIDENCE_THRESHOLD": "0.6",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session")
def storage_root() -> Path:
    return _TMP / "storage"


@pytest.fixture(scope="session")
async def app():
    from app.db.session import init_db
    from app.main import create_app

    await init_db()
    return create_app()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def register_and_login(client: httpx.AsyncClient, role: str = "physician") -> dict[str, str]:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    password = "correct-horse-battery"
    response = await client.post(
        f"{API}/auth/register", json={"email": email, "password": password, "full_name": "Dr Test", "role": role}
    )
    assert response.status_code == 201, response.text
    response = await client.post(f"{API}/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def auth_headers(client) -> dict[str, str]:
    return await register_and_login(client)


def make_png(size: tuple[int, int] = (64, 64)) -> bytes:
    image = Image.new("L", size)
    for x in range(size[0]):
        for y in range(size[1]):
            image.putpixel((x, y), (x * 4) % 256)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
