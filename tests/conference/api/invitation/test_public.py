from datetime import timedelta
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import Conference, Invitation
from app.conference.services import InvitationService
from app.core.models import User
from tests.helpers import approx_now


@pytest.mark.django_db
class TestLookupInvitation:
    path = reverse("api-1.0.0:lookup-invitation")

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            given_name="Alice",
            family_name="Smith",
            affiliation="MIT",
            region_code="US",
            desired_paper_count=3,
        )
        invitation.interested_keywords.create(text="machine-learning")
        token = InvitationService.get_invitation_token(invitation)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.OK

        assert response.json() == {
            "uid": str(invitation.uid),
            "state": Invitation.State.PENDING,
            "invitee_email": invitation.invitee_email,
            "given_name": "Alice",
            "family_name": "Smith",
            "affiliation": "MIT",
            "region_code": "US",
            "desired_paper_count": 3,
            "interested_keywords": ["machine-learning"],
            "conference": {
                "name": conference.name,
                "display_name": conference.display_name,
            },
            "has_existing_account": False,
            "token": token,
            "accept_url": (
                f"http://testserver{reverse('frontend:invitation-accept')}#{token}"
            ),
            "reject_url": (
                f"http://testserver{reverse('frontend:invitation-reject')}#{token}"
            ),
        }

    def test_invalid_token_returns_not_found(self, api_client: Client) -> None:
        response = api_client.post(self.path, data={"invitation_token": "bad-token"})
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_missing_invitation_returns_not_found(self, api_client: Client) -> None:
        token = InvitationService.token_signer.sign(str(ULID()))

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_has_existing_account_true_when_active_user_exists(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        email = faker.email()
        User.objects.create_user(username=faker.user_name(), email=email)
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=email,
        )
        token = InvitationService.get_invitation_token(invitation)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.OK

        assert response.json()["has_existing_account"] is True

    def test_has_existing_account_false_when_user_inactive(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        email = faker.email()
        User.objects.create_user(
            username=faker.user_name(),
            email=email,
            is_active=False,
        )
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=email,
        )
        token = InvitationService.get_invitation_token(invitation)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.OK

        assert response.json()["has_existing_account"] is False

    def test_has_existing_account_case_insensitive(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        User.objects.create_user(
            username=faker.user_name(),
            email="John.Doe@Example.COM",
        )
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email="john.doe@example.com",
        )
        token = InvitationService.get_invitation_token(invitation)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.OK

        assert response.json()["has_existing_account"] is True


@pytest.mark.django_db
class TestRedeemInvitation:
    path = reverse("api-1.0.0:redeem-invitation")

    @pytest.fixture
    def invitation_service_redeem(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(InvitationService, "redeem_invitation")

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        invitation_service_redeem: MagicMock,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        token = InvitationService.get_invitation_token(invitation)
        api_client.force_login(user)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation.refresh_from_db()
        assert invitation.state == Invitation.State.ACCEPTED
        assert invitation.accept_time == approx_now()
        assert invitation.invitee_user == user

        invitation_service_redeem.assert_called_once_with(invitation, user)

    def test_requires_authentication(self, api_client: Client) -> None:
        response = api_client.post(self.path, data={"invitation_token": "anything"})
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_invalid_token_returns_not_found(
        self,
        faker: Faker,
        api_client: Client,
        invitation_service_redeem: MagicMock,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.post(self.path, data={"invitation_token": "bad-token"})
        assert response.status_code == HTTPStatus.NOT_FOUND

        invitation_service_redeem.assert_not_called()

    def test_conflict_when_redeemed_by_other_user(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        current_user = User.objects.create_user(username=faker.user_name())
        original_user = User.objects.create_user(username=faker.user_name())
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            invitee_user=original_user,
            accept_time=timezone.now(),
        )
        token = InvitationService.get_invitation_token(invitation)
        api_client.force_login(current_user)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.CONFLICT


@pytest.mark.django_db
class TestRejectInvitation:
    path = reverse("api-1.0.0:reject-invitation")

    def test_happy_path(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
        )
        token = InvitationService.get_invitation_token(invitation)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation.refresh_from_db()
        assert invitation.reject_time == approx_now()
        assert invitation.state == Invitation.State.REJECTED

    def test_already_accepted_is_ignored(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            accept_time=timezone.now(),
        )
        token = InvitationService.get_invitation_token(invitation)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation.refresh_from_db()
        assert invitation.reject_time is None
        assert invitation.state == Invitation.State.ACCEPTED

    def test_already_rejected_is_ignored(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
    ) -> None:
        original_reject_time = timezone.now() - timedelta(hours=1)
        invitation = Invitation.objects.create(
            conference=conference,
            invitee_email=faker.email(),
            reject_time=original_reject_time,
        )
        token = InvitationService.get_invitation_token(invitation)

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation.refresh_from_db()
        assert invitation.reject_time == original_reject_time
        assert invitation.state == Invitation.State.REJECTED

    def test_missing_invitation_returns_no_content(self, api_client: Client) -> None:
        token = InvitationService.token_signer.sign(str(ULID()))

        response = api_client.post(self.path, data={"invitation_token": token})
        assert response.status_code == HTTPStatus.NO_CONTENT
