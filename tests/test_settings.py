from http import HTTPStatus
from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.test import Client
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from tests.base import URLConfTestCase, URLPatterns
from tests.data import INVALID_PASSWORDS, VALID_PASSWORDS


class TestCsrfCookie(URLConfTestCase):
    @staticmethod
    @ensure_csrf_cookie
    @require_GET
    def ensure_csrf(_: Any) -> HttpResponse:
        return HttpResponse()

    @staticmethod
    @require_POST
    def verify_csrf(_: Any) -> HttpResponse:
        return HttpResponse()

    @pytest.fixture
    def urlpatterns(self) -> URLPatterns:
        return [
            path("ensure-csrf/", self.ensure_csrf),
            path("verify-csrf/", self.verify_csrf),
        ]

    @pytest.fixture
    def csrf_client(self) -> Client:
        return Client(enforce_csrf_checks=True)

    @pytest.fixture
    def csrf_cookie_name(self, settings: LazySettings) -> str:
        return settings.CSRF_COOKIE_NAME

    @pytest.fixture
    def csrf_header_name(self, settings: LazySettings) -> str:
        return settings.CSRF_HEADER_NAME.removeprefix("HTTP_").replace("_", "-")

    def test_request_with_csrf(
        self,
        csrf_client: Client,
        csrf_cookie_name: str,
        csrf_header_name: str,
    ) -> None:
        assert csrf_cookie_name not in csrf_client.cookies
        response = csrf_client.get("/ensure-csrf/")
        assert response.status_code == HTTPStatus.OK

        csrf_cookie = csrf_client.cookies[csrf_cookie_name]
        assert csrf_cookie["secure"]
        assert not csrf_cookie["httponly"]

        response = csrf_client.post(
            "/verify-csrf/",
            headers={csrf_header_name: csrf_cookie.value},
        )
        assert response.status_code == HTTPStatus.OK

    def test_request_without_csrf(
        self,
        csrf_client: Client,
        csrf_cookie_name: str,
    ) -> None:
        assert csrf_cookie_name not in csrf_client.cookies
        response = csrf_client.post("/verify-csrf/")
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_request_with_invalid_csrf(
        self,
        csrf_client: Client,
        csrf_header_name: str,
    ) -> None:
        response = csrf_client.post(
            "/verify-csrf/",
            headers={csrf_header_name: "invalid"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


class TestAuthPasswordValidators:
    @pytest.mark.parametrize("password", VALID_PASSWORDS)
    def test_valid_password(self, password: str) -> None:
        validate_password(password)

    @pytest.mark.parametrize("password", INVALID_PASSWORDS)
    def test_invalid_password(self, password: str) -> None:
        with pytest.raises(DjangoValidationError):
            validate_password(password)
