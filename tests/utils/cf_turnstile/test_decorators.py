from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from django.conf import LazySettings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client
from django.urls import path
from faker import Faker
from pytest_mock import MockerFixture

from app.utils.cf_turnstile.decorators import cf_turnstile_required
from app.utils.cf_turnstile.types import CFTurnstileMode
from tests.base import URLConfTestCase, URLPatterns


class TestCfTurnstileRequired(URLConfTestCase):
    @staticmethod
    @cf_turnstile_required
    def protected_view(_: Any) -> HttpResponse:
        return HttpResponse()

    @staticmethod
    @cf_turnstile_required(enforce_on_safe=True)
    def protected_view_enforce_safe(_: Any) -> HttpResponse:
        return HttpResponse()

    @staticmethod
    @cf_turnstile_required
    async def async_protected_view(_: Any) -> HttpResponse:
        return HttpResponse()

    @pytest.fixture
    def urlpatterns(self) -> URLPatterns:
        return [
            path("protected/", self.protected_view),
            path("protected-safe/", self.protected_view_enforce_safe),
            path("async-protected/", self.async_protected_view),
        ]

    @pytest.fixture
    def mock_header_name(self, settings: LazySettings) -> str:
        name = "X-Turnstile"
        settings.CF_TURNSTILE_RESPONSE_HEADER_NAME = name
        return name

    @pytest.fixture
    def mock_verify(self, mocker: MockerFixture) -> AsyncMock:
        mock = mocker.patch(
            "app.utils.cf_turnstile.decorators.verify_cf_turnstile_response"
        )
        return mock

    @pytest.mark.parametrize("url", ["/protected/", "/async-protected/"])
    @pytest.mark.parametrize("method", ["get", "head", "options", "trace"])
    def test_safe_method_without_enforcement(
        self,
        client: Client,
        url: str,
        method: str,
    ) -> None:
        response = getattr(client, method)(url)
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("method", ["get", "options", "trace"])
    def test_safe_method_with_enforcement(
        self,
        client: Client,
        mock_header_name: str,
        method: str,
    ) -> None:
        response = getattr(client, method)("/protected-safe/")
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"message": f"Missing {mock_header_name} header."}

    @pytest.mark.parametrize(
        "url",
        ["/protected/", "/protected-safe/", "/async-protected/"],
    )
    def test_disabled_mode_bypasses_verification(
        self,
        settings: LazySettings,
        client: Client,
        mock_verify: AsyncMock,
        url: str,
    ) -> None:
        settings.CF_TURNSTILE_MODE = CFTurnstileMode.DISABLED

        response = client.post(url)

        assert response.status_code == HTTPStatus.OK
        mock_verify.assert_not_called()

    @pytest.mark.parametrize(
        "url",
        ["/protected/", "/protected-safe/", "/async-protected/"],
    )
    def test_unsafe_method(
        self,
        client: Client,
        mock_header_name: str,
        url: str,
    ) -> None:
        response = client.post(url)
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"message": f"Missing {mock_header_name} header."}

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "url",
        ["/protected/", "/protected-safe/", "/async-protected/"],
    )
    def test_valid_bypass_superuser(
        self,
        faker: Faker,
        client: Client,
        url: str,
    ) -> None:
        user = get_user_model().objects.create_superuser(username=faker.user_name())
        client.force_login(user)

        response = client.post(url)

        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize(
        "url",
        ["/protected/", "/protected-safe/", "/async-protected/"],
    )
    @pytest.mark.parametrize("location", ["data", "headers"])
    def test_valid_cf_turnstile_response(
        self,
        client: Client,
        mock_header_name: str,
        mock_verify: AsyncMock,
        url: str,
        location: str,
    ) -> None:
        mock_verify.return_value = True, {}

        response = client.post(
            url,
            **{  # type: ignore[arg-type]
                location: {mock_header_name: "test-response"},
            },
        )

        assert response.status_code == HTTPStatus.OK
        mock_verify.assert_called_once()

    @pytest.mark.parametrize(
        "url",
        ["/protected/", "/protected-safe/", "/async-protected/"],
    )
    @pytest.mark.parametrize("location", ["data", "headers"])
    def test_invalid_cf_turnstile_response(
        self,
        client: Client,
        mock_header_name: str,
        mock_verify: AsyncMock,
        url: str,
        location: str,
    ) -> None:
        mock_verify.return_value = False, {}

        response = client.post(
            url,
            **{  # type: ignore[arg-type]
                location: {mock_header_name: "test-response"},
            },
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"message": f"Invalid {mock_header_name} header."}
        mock_verify.assert_called_once()

    @pytest.mark.parametrize(
        "mock_verify_side_effect",
        [
            httpx.HTTPStatusError("Foobar", request=MagicMock(), response=MagicMock()),
            httpx.RequestError("Foobar"),
        ],
    )
    @pytest.mark.parametrize(
        "url",
        ["/protected/", "/protected-safe/", "/async-protected/"],
    )
    @pytest.mark.parametrize("location", ["data", "headers"])
    def test_cf_turnstile_api_error(
        self,
        client: Client,
        mock_header_name: str,
        mock_verify: AsyncMock,
        mock_verify_side_effect: Exception,
        url: str,
        location: str,
    ) -> None:
        mock_verify.side_effect = mock_verify_side_effect

        response = client.post(
            url,
            **{  # type: ignore[arg-type]
                location: {mock_header_name: "test-response"},
            },
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.json() == {"message": "CF Turnstile unavailable."}
        assert response.headers["Retry-After"] == "30"
        mock_verify.assert_called_once()
