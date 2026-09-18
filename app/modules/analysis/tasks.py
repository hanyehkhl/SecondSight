from fastapi import BackgroundTasks

from app.core.config import get_settings
from app.modules.analysis.service import run_analysis


def dispatch_analysis(analysis_id: str, background_tasks: BackgroundTasks) -> None:
    """Queue an analysis. `inline` runs after the HTTP response in the API process; `celery` uses the worker."""
    if get_settings().task_backend == "celery":
        from app.worker import run_analysis_task

        run_analysis_task.delay(analysis_id)
    else:
        background_tasks.add_task(run_analysis, analysis_id)
