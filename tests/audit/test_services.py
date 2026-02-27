import pytest
from faker import Faker
from ninja import Schema
from pydantic import SecretStr
from pytest_mock import MockerFixture

from app.audit.models import AuditLog
from app.audit.services import audit
from app.audit.types import Auditable, AuditResourceInfo
from app.core.models import User
from app.core.types import HttpRequest


class FakeAuditable(Auditable):
    def audit_resource_info(self) -> AuditResourceInfo:
        return AuditResourceInfo(
            resource="paper",  # type: ignore[typeddict-item]
            resource_id="01JEXAMPLE000000000000000",
            resource_label="My Paper Title",
        )


@pytest.mark.django_db(transaction=True)
class TestAudit:
    async def test_with_auditable_resource(self, authed_request: HttpRequest) -> None:
        await audit(
            request=authed_request,
            action="paper.create",  # type: ignore[arg-type]
            resource=FakeAuditable(),
            scope="CONF2025",
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.action == "paper.create"
        assert log.resource == "paper"
        assert log.resource_id == "01JEXAMPLE000000000000000"
        assert log.resource_label == "My Paper Title"
        assert log.scope == "CONF2025"
        assert log.ip_address == "203.0.113.1"
        assert log.request_id == "abc123"

    async def test_request_context_defaults(self, bare_request: HttpRequest) -> None:
        await audit(
            request=bare_request,
            action="paper.create",  # type: ignore[arg-type]
            resource="paper",  # type: ignore[arg-type]
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.ip_address is None
        assert log.request_id == ""

    async def test_with_enum_resource(
        self, authed_request: HttpRequest, user: User
    ) -> None:
        await audit(
            request=authed_request,
            action="session.create",  # type: ignore[arg-type]
            resource="session",  # type: ignore[arg-type]
            resource_id=str(user.uid),
            resource_label=user.email,
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.resource == "session"
        assert log.resource_id == str(user.uid)
        assert log.resource_label == user.email

    async def test_actor_resolved_from_request(
        self,
        authed_request: HttpRequest,
        user: User,
    ) -> None:
        await audit(
            request=authed_request,
            action="paper.create",  # type: ignore[arg-type]
            resource="paper",  # type: ignore[arg-type]
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.actor_uid == str(user.uid)
        assert log.actor_label == user.email or user.username

    async def test_actor_override(
        self,
        faker: Faker,
        authed_request: HttpRequest,
    ) -> None:
        admin = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )

        await audit(
            request=authed_request,
            action="session.assume",  # type: ignore[arg-type]
            resource="session",  # type: ignore[arg-type]
            actor=admin,
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.actor_uid == str(admin.uid)
        assert log.actor_label == admin.email

    async def test_anonymous_actor(self, anon_request: HttpRequest) -> None:
        await audit(
            request=anon_request,
            action="session.create_failed",  # type: ignore[arg-type]
            resource="session",  # type: ignore[arg-type]
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.actor_uid == ""
        assert log.actor_label == ""

    async def test_payload_and_detail(self, authed_request: HttpRequest) -> None:
        await audit(
            request=authed_request,
            action="paper.create",  # type: ignore[arg-type]
            resource="paper",  # type: ignore[arg-type]
            payload={"title": "My Paper"},
            detail={"state_before": "draft"},
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.payload == {"title": "My Paper"}
        assert log.detail == {"state_before": "draft"}

    async def test_payload_base_model(self, authed_request: HttpRequest) -> None:
        class LoginPayload(Schema):
            username: str
            password: SecretStr

        await audit(
            request=authed_request,
            action="session.create",  # type: ignore[arg-type]
            resource="session",  # type: ignore[arg-type]
            payload=LoginPayload(username="jdoe", password="s3cret"),  # type: ignore[arg-type] # noqa: S106
        )

        log = await AuditLog.objects.alatest("timestamp")
        assert log.payload["username"] == "jdoe"
        assert "s3cret" not in log.payload["password"]

    @pytest.mark.expect_audit_error
    async def test_exception_swallowed(
        self,
        mocker: MockerFixture,
        authed_request: HttpRequest,
    ) -> None:
        mocker.patch.object(
            AuditLog.objects,
            "acreate",
            side_effect=RuntimeError("db down"),
        )

        await audit(
            request=authed_request,
            action="paper.create",  # type: ignore[arg-type]
            resource="paper",  # type: ignore[arg-type]
        )

        assert await AuditLog.objects.acount() == 0
