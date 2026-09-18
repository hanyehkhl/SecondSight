from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    actor_id: str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """Append an audit entry. `actor_id=None` means the system itself (e.g. the analysis worker).

    Details must never contain clinical content (questions, findings, reports); only identifiers and outcomes.
    """
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=request.client.host if request and request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:255] if request else None,
            details=details or {},
        )
    )
    if commit:
        await db.commit()
