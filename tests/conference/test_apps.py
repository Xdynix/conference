from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker

from app.conference.models import UserProfile
from app.core.models import User
from app.utils.enums import Region
from app.verikit.services import EmailVerificationService


@pytest.fixture(autouse=True)
def mock_cf_turnstile(mock_cf_turnstile: MagicMock) -> MagicMock:
    return mock_cf_turnstile


@pytest.mark.django_db
class TestProfileInjectionInSessionEndpoints:
    get_session_path = reverse("api-1.0.0:get-session")
    create_session_path = reverse("api-1.0.0:create-session")

    @pytest.fixture
    def password(self, faker: Faker) -> str:
        return faker.password()

    @pytest.fixture
    def user_without_profile(self, faker: Faker, password: str) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=password,
        )

    @pytest.fixture
    def user_with_profile(self, faker: Faker, password: str) -> User:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
            password=password,
        )
        UserProfile.objects.create(
            user=user,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            affiliation=faker.company(),
            region_code=Region.US.name,
        )
        return user

    @pytest.fixture
    def serialized_profile(self, user_with_profile: User) -> dict[str, Any]:
        profile = user_with_profile.profile
        return {
            "given_name": profile.given_name,
            "family_name": profile.family_name,
            "affiliation": profile.affiliation,
            "region_code": profile.region_code,
        }

    def test_get_session_includes_profile_when_exists(
        self,
        api_client: Client,
        user_with_profile: User,
        serialized_profile: dict[str, Any],
    ) -> None:
        api_client.force_login(user_with_profile)

        response = api_client.get(self.get_session_path)

        assert response.status_code == HTTPStatus.OK
        data = response.json()

        user_data = data["user"]
        assert user_data["uid"] == str(user_with_profile.uid)
        assert user_data["username"] == user_with_profile.username
        assert user_data["email"] == user_with_profile.email
        assert user_data["profile"] == serialized_profile

    def test_get_session_has_null_profile_when_missing(
        self,
        api_client: Client,
        user_without_profile: User,
    ) -> None:
        api_client.force_login(user_without_profile)

        response = api_client.get(self.get_session_path)

        assert response.status_code == HTTPStatus.OK
        data = response.json()

        user_data = data["user"]
        assert user_data["username"] == user_without_profile.username
        assert "profile" not in user_data

    def test_create_session_includes_profile(
        self,
        api_client: Client,
        password: str,
        user_with_profile: User,
        serialized_profile: dict[str, Any],
    ) -> None:
        response = api_client.post(
            self.create_session_path,
            data={
                "username": user_with_profile.username,
                "password": password,
            },
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()

        user_data = data["user"]
        assert user_data["uid"] == str(user_with_profile.uid)
        assert user_data["profile"] == serialized_profile

    def test_create_session_null_profile_when_missing(
        self,
        api_client: Client,
        password: str,
        user_without_profile: User,
    ) -> None:
        response = api_client.post(
            self.create_session_path,
            data={
                "username": user_without_profile.username,
                "password": password,
            },
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()

        user_data = data["user"]
        assert user_data["uid"] == str(user_without_profile.uid)
        assert "profile" not in user_data


@pytest.mark.django_db
class TestProfileInjectionInUserCreationEndpoints:
    create_registration_path = reverse("api-1.0.0:create-registration")
    create_user_path = reverse("api-1.0.0:create-user")

    @pytest.fixture
    def admin_user(self, faker: Faker) -> User:
        return User.objects.create_superuser(username=faker.user_name())

    @pytest.fixture
    def profile_payload(self, faker: Faker) -> dict[str, Any]:
        return {
            "given_name": faker.first_name(),
            "family_name": faker.last_name(),
            "affiliation": faker.company(),
            "region_code": Region.US.name,
        }

    def test_create_registration_with_profile(
        self,
        faker: Faker,
        api_client: Client,
        profile_payload: dict[str, Any],
    ) -> None:
        username = faker.user_name()
        email_token = EmailVerificationService.issue_token(faker.email())
        password = faker.password()

        response = api_client.post(
            self.create_registration_path,
            data={
                "username": username,
                "email": email_token,
                "password": password,
                "profile": profile_payload,
            },
        )

        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        profile_data = data["user"]["profile"]

        profile = UserProfile.objects.filter(user__username=username).get()
        for field in ("given_name", "family_name", "affiliation", "region_code"):
            assert (
                getattr(profile, field) == profile_data[field] == profile_payload[field]
            )

    def test_create_registration_with_empty_profile(
        self,
        faker: Faker,
        api_client: Client,
    ) -> None:
        username = faker.user_name()
        email_token = EmailVerificationService.issue_token(faker.email())
        password = faker.password()

        response = api_client.post(
            self.create_registration_path,
            data={
                "username": username,
                "email": email_token,
                "password": password,
            },
        )

        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        profile_data = data["user"]["profile"]

        profile = UserProfile.objects.filter(user__username=username).get()
        for field in ("given_name", "family_name", "affiliation", "region_code"):
            assert getattr(profile, field) == profile_data[field] == ""

    def test_create_user_with_profile(
        self,
        faker: Faker,
        api_client: Client,
        admin_user: User,
        profile_payload: dict[str, Any],
    ) -> None:
        api_client.force_login(admin_user)

        username = faker.user_name()
        email = faker.email()
        password = faker.password()

        response = api_client.post(
            self.create_user_path,
            data={
                "username": username,
                "email": email,
                "password": password,
                "profile": profile_payload,
            },
        )

        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        profile_data = data["profile"]

        profile = UserProfile.objects.filter(user__username=username).get()
        for field in ("given_name", "family_name", "affiliation", "region_code"):
            assert (
                getattr(profile, field) == profile_data[field] == profile_payload[field]
            )

    def test_create_user_with_empty_profile(
        self,
        faker: Faker,
        api_client: Client,
        admin_user: User,
    ) -> None:
        api_client.force_login(admin_user)

        username = faker.user_name()
        email = faker.email()
        password = faker.password()

        response = api_client.post(
            self.create_user_path,
            data={
                "username": username,
                "email": email,
                "password": password,
            },
        )

        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        profile_data = data["profile"]

        profile = UserProfile.objects.filter(user__username=username).get()
        for field in ("given_name", "family_name", "affiliation", "region_code"):
            assert getattr(profile, field) == profile_data[field] == ""
