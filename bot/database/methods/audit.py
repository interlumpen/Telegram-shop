import logging

from bot.database.main import Database
from bot.database.models.main import AuditLog
from bot.logger_mesh import audit_logger

_LOG_LEVELS = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def log_audit(
    action: str,
    *,
    level: str = "INFO",
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Write audit entry to both the log file and the database.

    NOTE: This function is intentionally kept synchronous so it can be called
    from both sync (inside transactions/executor) and async contexts.
    Callers in async context should use ``run_in_executor`` if needed, but
    audit logging is typically fire-and-forget and fast enough to inline.
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
        with Database().session() as s:
            s.add(entry)
    except Exception:
        audit_logger.debug("Failed to write audit entry to DB", exc_info=True)
