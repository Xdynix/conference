from http import HTTPStatus
from typing import Any, cast

import pytest
from django.conf import LazySettings
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.verikit.services import EmailVerificationService
from tests.helpers import update_object


def extract_token_from_email(email_body: str, link_type: str) -> str:
    """Extract invitation token from email body.

    Args:
        email_body: The email body containing accept/reject links.
        link_type: Either "accept" or "reject" to specify which link to extract.

    Returns:
        The invitation token from the specified link.
    """
    for line in email_body.splitlines():
        if line.startswith(f"{link_type.capitalize()}: "):
            link = line.split(": ", 1)[1].strip()
            return link.split("#", 1)[1]
    raise ValueError(f"Could not find {link_type} link in email body.")


@pytest.mark.django_db(transaction=True)
class TestInvitationE2E:
    lookup_invitation_path = reverse("api-1.0.0:lookup-invitation")
    redeem_invitation_path = reverse("api-1.0.0:redeem-invitation")
    reject_invitation_path = reverse("api-1.0.0:reject-invitation")
    create_registration_path = reverse("api-1.0.0:create-registration")

    @classmethod
    def create_invitation_path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-invitation", args=[conference_name])

    @classmethod
    def send_invitations_path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:send-invitations", args=[conference_name])

    @pytest.fixture(autouse=True)
    def invitation_page_uris(self, settings: LazySettings) -> None:
        settings.INVITATION_ACCEPT_PAGE_URL = "https://example.com/accept"
        settings.INVITATION_REJECT_PAGE_URL = "https://example.com/reject"

    @pytest.fixture(autouse=True)
    def mock_cf_turnstile(self, mock_cf_turnstile: None) -> None:
        pass

    @pytest.fixture
    def global_admin(self, faker: Faker) -> User:
        user = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        return user

    @pytest.fixture
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.PUBLIC,
        )

    @pytest.fixture
    def track(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )

    @pytest.fixture
    def conference_admin(self, faker: Faker, conference: Conference) -> User:
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        return user

    def create_and_send_invitation(
        self,
        api_client: Client,
        conference: Conference,
        admin: User,
        invitee_email: str,
        *,
        conference_roles: list[ConferenceRole] | None = None,
        track_roles: list[dict[str, str]] | None = None,
    ) -> str:
        """Create an invitation and send the email.

        Returns:
            The invitation UID as a string.
        """
        api_client.force_login(admin)

        payload: dict[str, Any] = {
            "invitee_email": invitee_email,
            "given_name": "Test",
            "family_name": "Invitee",
        }
        if conference_roles:
            payload["conference_roles"] = [r.value for r in conference_roles]
        if track_roles:
            payload["track_roles"] = track_roles

        response = api_client.post(
            self.create_invitation_path(conference.name),
            data=payload,
        )
        assert response.status_code == HTTPStatus.CREATED
        invitation_uid = response.json()["uid"]

        response = api_client.post(
            self.send_invitations_path(conference.name),
            data={
                "subject": "Invitation",
                "body": "Accept: {{ accept_url }}\nReject: {{ reject_url }}",
                "invitation_uids": [invitation_uid],
                "force_send_to_recent": True,
            },
        )
        assert response.status_code == HTTPStatus.OK

        api_client.logout()
        return cast(str, invitation_uid)

    def test_create_and_redeem_with_existing_account(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        invitee_email = faker.email()
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=invitee_email,
            password=faker.password(),
        )

        invitation_uid = self.create_and_send_invitation(
            api_client,
            conference,
            conference_admin,
            invitee_email,
            conference_roles=[ConferenceRole.REVIEWER],
        )

        [sent_email] = mailoutbox
        assert sent_email.to == [invitee_email]
        token = extract_token_from_email(str(sent_email.body), "accept")

        response = api_client.post(
            self.lookup_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["uid"] == invitation_uid
        assert data["status"] == Invitation.Status.PENDING
        assert data["invitee_email"] == invitee_email
        assert data["conference"]["name"] == conference.name

        api_client.force_login(existing_user)
        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation = Invitation.objects.get(uid=invitation_uid)
        assert invitation.status == Invitation.Status.ACCEPTED
        assert invitation.invitee_user == existing_user

        assert ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=existing_user,
            role=ConferenceRole.REVIEWER,
        ).exists()

    def test_create_and_redeem_with_new_registration(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_admin: User,
        track: Track,
    ) -> None:
        invitee_email = faker.email()

        invitation_uid = self.create_and_send_invitation(
            api_client,
            conference,
            conference_admin,
            invitee_email,
            conference_roles=[ConferenceRole.REVIEWER],
            track_roles=[{"uid": str(track.uid), "role": TrackRole.REVIEWER}],
        )

        [sent_email] = mailoutbox
        assert sent_email.to == [invitee_email]
        invitation_token = extract_token_from_email(str(sent_email.body), "accept")

        email_verification_token = EmailVerificationService.issue_token(invitee_email)
        new_username = faker.user_name()
        new_password = faker.password()

        response = api_client.post(
            self.create_registration_path,
            data={
                "username": new_username,
                "email": email_verification_token,
                "password": new_password,
                "invitation_token": invitation_token,
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        new_user_uid = response.json()["user"]["uid"]

        invitation = Invitation.objects.get(uid=invitation_uid)
        assert invitation.status == Invitation.Status.ACCEPTED
        assert invitation.invitee_user is not None
        assert str(invitation.invitee_user.uid) == new_user_uid

        new_user = User.objects.get(uid=new_user_uid)
        assert ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=new_user,
            role=ConferenceRole.REVIEWER,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            track=track,
            user=new_user,
            role=TrackRole.REVIEWER,
        ).exists()

    def test_create_and_reject_flow(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        invitee_email = faker.email()

        invitation_uid = self.create_and_send_invitation(
            api_client,
            conference,
            conference_admin,
            invitee_email,
            conference_roles=[ConferenceRole.REVIEWER],
        )

        [sent_email] = mailoutbox
        token = extract_token_from_email(str(sent_email.body), "reject")

        response = api_client.post(
            self.reject_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation = Invitation.objects.get(uid=invitation_uid)
        assert invitation.status == Invitation.Status.REJECTED
        assert invitation.reject_time is not None
        assert invitation.accept_time is None
        assert invitation.invitee_user is None

        assert (
            not ConferenceRoleAssignment.objects.filter(
                conference=conference,
                role=ConferenceRole.REVIEWER,
            )
            .exclude(user=conference_admin)
            .exists()
        )

    def test_redeem_previously_rejected_invitation(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        invitee_email = faker.email()
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=invitee_email,
            password=faker.password(),
        )

        invitation_uid = self.create_and_send_invitation(
            api_client,
            conference,
            conference_admin,
            invitee_email,
            conference_roles=[ConferenceRole.REVIEWER],
        )

        [sent_email] = mailoutbox
        reject_token = extract_token_from_email(str(sent_email.body), "reject")
        accept_token = extract_token_from_email(str(sent_email.body), "accept")

        response = api_client.post(
            self.reject_invitation_path,
            data={"invitation_token": reject_token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation = Invitation.objects.get(uid=invitation_uid)
        assert invitation.status == Invitation.Status.REJECTED

        api_client.force_login(existing_user)
        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": accept_token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        # mypy narrows `invitation.status` to `REJECTED` after the earlier assertion.
        # Re-fetch a new instance instead of calling `refresh_from_db()` to avoid that
        # false positive.
        invitation = Invitation.objects.get(pk=invitation.pk)
        assert invitation.status == Invitation.Status.ACCEPTED
        assert invitation.invitee_user == existing_user
        assert invitation.accept_time is not None
        assert invitation.reject_time is not None

        assert ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=existing_user,
            role=ConferenceRole.REVIEWER,
        ).exists()

    def test_cannot_redeem_invitation_accepted_by_another_user(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        invitee_email = faker.email()
        first_user = User.objects.create_user(
            username=faker.user_name(),
            email=invitee_email,
            password=faker.password(),
        )
        second_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=faker.password(),
        )

        self.create_and_send_invitation(
            api_client,
            conference,
            conference_admin,
            invitee_email,
            conference_roles=[ConferenceRole.REVIEWER],
        )

        [sent_email] = mailoutbox
        token = extract_token_from_email(str(sent_email.body), "accept")

        api_client.force_login(first_user)
        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        api_client.force_login(second_user)
        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert "already redeemed by another user" in response.json()["message"]

    def test_same_user_can_redeem_already_accepted_invitation(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        invitee_email = faker.email()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=invitee_email,
            password=faker.password(),
        )

        self.create_and_send_invitation(
            api_client,
            conference,
            conference_admin,
            invitee_email,
            conference_roles=[ConferenceRole.REVIEWER],
        )

        [sent_email] = mailoutbox
        token = extract_token_from_email(str(sent_email.body), "accept")

        api_client.force_login(user)
        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        assert (
            ConferenceRoleAssignment.objects.filter(
                conference=conference,
                user=user,
                role=ConferenceRole.REVIEWER,
            ).count()
            == 1
        )

    def test_invalid_token_returns_not_found(
        self,
        api_client: Client,
        faker: Faker,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": "invalid-token"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_invitation_for_inactive_conference_cannot_be_redeemed(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        conference_admin: User,
    ) -> None:
        invitee_email = faker.email()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=invitee_email,
            password=faker.password(),
        )

        self.create_and_send_invitation(
            api_client,
            conference,
            conference_admin,
            invitee_email,
        )

        [sent_email] = mailoutbox
        token = extract_token_from_email(str(sent_email.body), "accept")

        update_object(conference, active=False)

        api_client.force_login(user)
        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_complete_flow_with_multiple_roles(
        self,
        faker: Faker,
        mailoutbox: list[EmailMessage],
        api_client: Client,
        conference: Conference,
        global_admin: User,
        track: Track,
    ) -> None:
        second_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        invitee_email = faker.email()
        user = User.objects.create_user(
            username=faker.user_name(),
            email=invitee_email,
            password=faker.password(),
        )

        invitation_uid = self.create_and_send_invitation(
            api_client,
            conference,
            global_admin,
            invitee_email,
            conference_roles=[ConferenceRole.REVIEWER, ConferenceRole.SECRETARY],
            track_roles=[
                {"uid": str(track.uid), "role": TrackRole.CHAIR},
                {"uid": str(track.uid), "role": TrackRole.REVIEWER},
                {"uid": str(second_track.uid), "role": TrackRole.REVIEWER},
            ],
        )

        [sent_email] = mailoutbox
        token = extract_token_from_email(str(sent_email.body), "accept")

        api_client.force_login(user)
        response = api_client.post(
            self.redeem_invitation_path,
            data={"invitation_token": token},
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        invitation = Invitation.objects.get(uid=invitation_uid)
        assert invitation.status == Invitation.Status.ACCEPTED

        assert ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=user,
            role=ConferenceRole.REVIEWER,
        ).exists()
        assert ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        ).exists()

        assert TrackRoleAssignment.objects.filter(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            track=track,
            user=user,
            role=TrackRole.REVIEWER,
        ).exists()
        assert TrackRoleAssignment.objects.filter(
            track=second_track,
            user=user,
            role=TrackRole.REVIEWER,
        ).exists()
