from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.conference.models import Profile
from app.core.models import User
from app.utils.enums import Region
from tests.helpers import update_object


@pytest.fixture
def profile_payload(faker: Faker) -> dict[str, str]:
    return {
        "given_name": faker.first_name(),
        "family_name": faker.last_name(),
        "affiliation": faker.company(),
        "region_code": "US",
    }


@pytest.mark.django_db
class TestUpdateCurrentUserProfile:
    path = reverse("api-1.0.0:update-current-user-profile")

    def test_creates_profile_when_missing(
        self,
        api_client: Client,
        user: User,
        profile_payload: dict[str, str],
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(self.path, data=profile_payload)
        assert response.status_code == HTTPStatus.OK

        profile = Profile.objects.get(user=user)
        for field, value in profile_payload.items():
            assert getattr(profile, field) == value
        assert response.json()["profile"] == profile_payload

    def test_trims_whitespace(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={
                "given_name": "  Ada  ",
                "family_name": "  Lovelace ",
                "affiliation": "  Analytical Engines  ",
                "region_code": "GB",
            },
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["profile"] == {
            "given_name": "Ada",
            "family_name": "Lovelace",
            "affiliation": "Analytical Engines",
            "region_code": "GB",
        }

        profile = Profile.objects.get(user=user)
        assert profile.given_name == "Ada"
        assert profile.family_name == "Lovelace"
        assert profile.affiliation == "Analytical Engines"

    def test_partial_update_existing_profile(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        profile = Profile.objects.create(
            user=user,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            affiliation=faker.company(),
            region_code=Region.CA.name,
        )
        original_family_name = profile.family_name
        original_affiliation = profile.affiliation
        new_given_name = faker.first_name()
        new_region_code = Region.DE.name
        api_client.force_login(user)

        response = api_client.patch(
            self.path,
            data={
                "given_name": new_given_name,
                "region_code": new_region_code,
            },
        )
        assert response.status_code == HTTPStatus.OK

        profile.refresh_from_db()
        assert profile.given_name == new_given_name
        assert profile.region_code == new_region_code
        assert profile.family_name == original_family_name
        assert profile.affiliation == original_affiliation
        assert response.json()["profile"] == {
            "given_name": new_given_name,
            "family_name": original_family_name,
            "affiliation": original_affiliation,
            "region_code": new_region_code,
        }

    def test_empty_payload_does_not_create_profile(
        self,
        api_client: Client,
        user: User,
    ) -> None:
        api_client.force_login(user)

        response = api_client.patch(self.path, data={})
        assert response.status_code == HTTPStatus.OK

        assert not Profile.objects.filter(user=user).exists()
        assert "profile" not in response.json()

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        profile_payload: dict[str, str],
    ) -> None:
        response = api_client.patch(self.path, data=profile_payload)
        assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
class TestUpdateProfile:
    @classmethod
    def path(cls, user_id: ULID) -> str:
        return reverse("api-1.0.0:update-profile", args=[user_id])

    def test_admin_updates_profile(
        self,
        api_client: Client,
        global_admin: User,
        user: User,
        profile_payload: dict[str, str],
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(user.uid),
            data=profile_payload,
        )
        assert response.status_code == HTTPStatus.OK

        profile = Profile.objects.get(user=user)
        for field, value in profile_payload.items():
            assert getattr(profile, field) == value
        assert response.json()["profile"] == profile_payload

    def test_inactive_user_not_found(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        user: User,
    ) -> None:
        update_object(user, is_active=False)
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(user.uid),
            data={"given_name": faker.first_name()},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        assert not Profile.objects.filter(user=user).exists()

    def test_unauthorized_user_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        user: User,
    ) -> None:
        another_user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(another_user)

        response = api_client.patch(
            self.path(user.uid),
            data={"given_name": faker.first_name()},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_empty_payload_does_not_create_profile(
        self,
        api_client: Client,
        global_admin: User,
        user: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(self.path(user.uid), data={})
        assert response.status_code == HTTPStatus.OK

        assert not Profile.objects.filter(user=user).exists()
