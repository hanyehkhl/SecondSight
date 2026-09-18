import logging

import httpx

from app.core.config import get_settings
from app.models.analysis import Analysis

logger = logging.getLogger(__name__)


async def notify_analysis_finished(analysis: Analysis) -> None:
    """Tell the requesting physician/clinic that a result is ready.

    The payload carries identifiers and status only; recipients fetch the report through the
    authenticated API, so no clinical content leaves the system through this channel.
    """
    payload = {
        "event": "analysis.finished",
        "analysis_id": analysis.id,
        "owner_id": analysis.owner_id,
        "status": analysis.status.value,
        "needs_human_review": analysis.needs_human_review,
    }
    url = get_settings().notification_webhook_url
    if not url:
        logger.info("Analysis %s finished with status %s", analysis.id, analysis.status.value)
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        # Notification is best effort; the result is already persisted.
        logger.warning("Notification webhook failed for analysis %s: %s", analysis.id, exc)
