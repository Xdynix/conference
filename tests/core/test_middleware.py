from http import HTTPStatus
from typing import Any

import pytest
from django.http import HttpResponse, JsonResponse
from django.test import AsyncClient, Client
from django.urls import path
from faker import Faker

from app.core.models import User
from app.core.services.api_key import ApiKeyService
from tests.base import URLConfTestCase, URLPatterns
from tests.helpers import approx_now, update_object


def sync_view(request: Any) -> HttpResponse:
    return JsonResponse({"username": request.user.username})


async def async_view(request: Any) -> HttpResponse:
    user = await request.auser()
    return JsonResponse({"username": user.username})


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        password=faker.password(),
        email=faker.email(),
    )


@pytest.fixture
def api_key_plaintext(user: User) -> str:
    _, plaintext = ApiKeyService.create_key(user)
    return plaintext


@pytest.mark.django_db
class TestApiKeyAuthMiddlewareSync(URLConfTestCase):
    url = "/sync/"

    @pytest.fixture
    def urlpatterns(self) -> URLPatterns:
        return [path("sync/", sync_view)]

    def test_valid_bearer_authenticates(
        self,
        client: Client,
        user: User,
        api_key_plaintext: str,
    ) -> None:
        response = client.get(self.url, headers=bearer_headers(api_key_plaintext))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == user.username

    def test_invalid_bearer_returns_401(self, client: Client) -> None:
        response = client.get(self.url, headers=bearer_headers("cfk_invalid"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"message": "Invalid credentials."}
        assert response["WWW-Authenticate"] == "Bearer"

    def test_no_bearer_passes_through(self, client: Client) -> None:
        response = client.get(self.url)
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == ""

    def test_non_cfk_bearer_ignored(self, client: Client) -> None:
        response = client.get(
            self.url,
            headers={"Authorization": "Bearer some_other_token"},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == ""

    def test_csrf_exempt(self, user: User, api_key_plaintext: str) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(self.url, headers=bearer_headers(api_key_plaintext))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == user.username

    def test_csrf_still_enforced_without_bearer(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(self.url)
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db(transaction=True)
class TestApiKeyAuthMiddlewareAsync(URLConfTestCase):
    url = "/async/"

    @pytest.fixture
    def urlpatterns(self) -> URLPatterns:
        return [path("async/", async_view)]

    async def test_valid_bearer_authenticates(
        self,
        async_client: AsyncClient,
        user: User,
        api_key_plaintext: str,
    ) -> None:
        response = await async_client.get(
            self.url,
            headers=bearer_headers(api_key_plaintext),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == user.username

    async def test_invalid_bearer_returns_401(self, async_client: AsyncClient) -> None:
        response = await async_client.get(
            self.url,
            headers=bearer_headers("cfk_invalid"),
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"message": "Invalid credentials."}
        assert response["WWW-Authenticate"] == "Bearer"

    async def test_no_bearer_passes_through(self, async_client: AsyncClient) -> None:
        response = await async_client.get(self.url)
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == ""

    async def test_non_cfk_bearer_ignored(self, async_client: AsyncClient) -> None:
        response = await async_client.get(
            self.url,
            headers={"Authorization": "Bearer some_other_token"},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == ""

    async def test_csrf_exempt(self, user: User, api_key_plaintext: str) -> None:
        csrf_client = AsyncClient(enforce_csrf_checks=True)
        response = await csrf_client.post(
            self.url,
            headers=bearer_headers(api_key_plaintext),
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == user.username

    async def test_csrf_still_enforced_without_bearer(self) -> None:
        csrf_client = AsyncClient(enforce_csrf_checks=True)
        response = await csrf_client.post(self.url)
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestApiKeyAuthBehavior(URLConfTestCase):
    url = "/sync/"

    @pytest.fixture
    def urlpatterns(self) -> URLPatterns:
        return [path("sync/", sync_view)]

    def test_revoked_key_returns_401(
        self,
        client: Client,
        user: User,
        api_key_plaintext: str,
    ) -> None:
        ApiKeyService.revoke_key(user)

        response = client.get(self.url, headers=bearer_headers(api_key_plaintext))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_inactive_user_returns_401(
        self,
        client: Client,
        user: User,
        api_key_plaintext: str,
    ) -> None:
        update_object(user, is_active=False)

        response = client.get(self.url, headers=bearer_headers(api_key_plaintext))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_invalid_bearer_rejects_despite_valid_session(
        self,
        client: Client,
        faker: Faker,
    ) -> None:
        other_user = User.objects.create_user(username=faker.user_name())
        client.force_login(other_user)

        response = client.get(self.url, headers=bearer_headers("cfk_invalid"))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_bearer_wins_over_session(
        self,
        client: Client,
        user: User,
        api_key_plaintext: str,
        faker: Faker,
    ) -> None:
        other_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        client.force_login(other_user)

        response = client.get(self.url, headers=bearer_headers(api_key_plaintext))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["username"] == user.username

    def test_updates_last_use_time(
        self,
        client: Client,
        user: User,
        api_key_plaintext: str,
    ) -> None:
        api_key = ApiKeyService.get_current_key(user)
        assert api_key is not None
        assert api_key.last_use_time is None

        client.get(self.url, headers=bearer_headers(api_key_plaintext))

        api_key.refresh_from_db()
        assert api_key.last_use_time == approx_now()
