from datetime import UTC, datetime

from app.audit.models import AuditLog


class TestAuditLog:
    def test_str_with_actor_label(self) -> None:
        log = AuditLog(
            timestamp=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
            action="paper.create",
            actor_uid="01JEXAMPLE000000000000000",
            actor_label="Jane Doe",
        )
        assert str(log) == "2025-01-15 12:00:00+00:00 paper.create by Jane Doe"

    def test_str_with_actor_uid_only(self) -> None:
        log = AuditLog(
            timestamp=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
            action="paper.create",
            actor_uid="01JEXAMPLE000000000000000",
        )
        assert (
            str(log)
            == "2025-01-15 12:00:00+00:00 paper.create by 01JEXAMPLE000000000000000"
        )

    def test_str_anonymous(self) -> None:
        log = AuditLog(
            timestamp=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
            action="session.create_failed",
        )
        assert (
            str(log) == "2025-01-15 12:00:00+00:00 session.create_failed by anonymous"
        )
