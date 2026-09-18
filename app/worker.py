"""Celery worker: `celery -A app.worker worker --loglevel=info --concurrency=1`.

Models are loaded once per worker process; keep concurrency at 1 per GPU.
"""

import asyncio

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery("secondsight", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True)

_loop: asyncio.AbstractEventLoop | None = None


def _run(coro):
    # One persistent loop per worker process so the async DB engine's connections stay valid across tasks.
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coro)


@celery_app.task(name="analysis.run")
def run_analysis_task(analysis_id: str) -> None:
    from app.modules.analysis.service import run_analysis

    _run(run_analysis(analysis_id))
