import pytest
from bot.database.methods.audit import log_audit
from bot.database.main import Database
from bot.database.models.main import AuditLog


class TestLogAudit:

    def test_creates_audit_record(self):
        log_audit("test_action", user_id=12345, details="test details")

        with Database().session() as s:
            entry = s.query(AuditLog).filter(AuditLog.action == "test_action").first()
            assert entry is not None
            assert entry.user_id == 12345
            assert entry.details == "test details"
            assert entry.level == "INFO"

    def test_warning_level(self):
        log_audit("warn_action", level="WARNING", details="warning test")

        with Database().session() as s:
            entry = s.query(AuditLog).filter(AuditLog.action == "warn_action").first()
            assert entry is not None
            assert entry.level == "WARNING"

    def test_all_optional_fields(self):
        log_audit(
            "full_action",
            level="ERROR",
            user_id=99999,
            resource_type="payment",
            resource_id="PAY-123",
            details="full test",
            ip_address="192.168.1.1",
        )

        with Database().session() as s:
            entry = s.query(AuditLog).filter(AuditLog.action == "full_action").first()
            assert entry is not None
            assert entry.resource_type == "payment"
            assert entry.resource_id == "PAY-123"
            assert entry.ip_address == "192.168.1.1"
            assert entry.level == "ERROR"

    def test_minimal_fields(self):
        log_audit("minimal_action")

        with Database().session() as s:
            entry = s.query(AuditLog).filter(AuditLog.action == "minimal_action").first()
            assert entry is not None
            assert entry.user_id is None
            assert entry.resource_type is None
            assert entry.details is None
            assert entry.ip_address is None
            assert entry.timestamp is not None
