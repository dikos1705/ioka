from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import AuditKind
from app.infrastructure.models import AuditLog


def add_status_audit(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    before: str | None,
    after: str,
) -> None:
    session.add(
        AuditLog(
            kind=AuditKind.STATUS_CHANGE,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_payload={"before": before},
            response_payload={"after": after},
            status_code=200,
        )
    )


def add_provider_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None,
    duration_ms: int,
    status_code: int,
    error_message: str | None = None,
) -> None:
    session.add(
        AuditLog(
            kind=AuditKind.PROVIDER_REQUEST,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            status_code=status_code,
            error_message=error_message,
        )
    )
