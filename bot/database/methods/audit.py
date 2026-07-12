import logging

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.main import Database
from bot.database.models.main import AuditLog
from bot.logger_mesh import audit_logger

_LOG_LEVELS = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


async def log_audit(
    action: str,
    *,
    level: str = "INFO",
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: str | None = None,
    ip_address: str | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Write audit entry to both the log file and the database.

    When 'session' is given, the DB row is added to that session so it
    commits (or rolls back) atomically with the caller's transaction. It avoids a phantom audit
    row surviving a rolled-back parent and avoids taking a second pooled
    connection while row locks are held. When 'session' is 'None' (the
    default), a dedicated short-lived session is opened and committed on its own.
    """
    # 1. File log
    log_level = _LOG_LEVELS.get(level, logging.INFO)
    parts = [f"action={action}"]
    if user_id is not None:
        parts.append(f"user={user_id}")
    if resource_type:
        parts.append(f"resource={resource_type}")
    if resource_id:
        parts.append(f"id={resource_id}")
    if details:
        parts.append(details)
    if ip_address:
        parts.append(f"ip={ip_address}")
    audit_logger.log(log_level, " | ".join(parts))

    # 2. Database log
    try:
        entry = AuditLog(
            level=level,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
        )
        if session is not None:
            # Enlist in the caller's transaction; the caller's commit/rollback
            # decides this row's fate.
            session.add(entry)
        else:
            async with Database().session() as s:
                s.add(entry)
    except Exception:
        audit_logger.warning("Failed to write audit entry to DB", exc_info=True)
