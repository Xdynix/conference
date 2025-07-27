from http import HTTPStatus
from typing import Any, NoReturn

import pytest
from django.http import Http404
from django.test import Client
from django.urls import path
from ninja import NinjaAPI, Schema
from ninja.errors import AuthorizationError, HttpError

from tests.base import URLConfTestCase, URLPatterns


class TestOasisAPIErrorHandling(URLConfTestCase):
    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        @api.get("/exception")
        def exception(*_: Any) -> NoReturn:
            raise RuntimeError

        @api.get("/404")
        def _404(*_: Any) -> NoReturn:
            raise Http404

        @api.get("/http-error")
        def http_error(*_: Any) -> NoReturn:
            raise HttpError(
                status_code=HTTPStatus.IM_A_TEAPOT,
                message="Something went wrong.",
            )

        class Foobar(Schema):
            foo: str
            bar: str

        @api.post("/validation-error")
        def validation_error(*_: Any, payload: Foobar) -> str:
            return payload.foo + payload.bar

        @api.get("/authorization-error")
        def authorization_error(*_: Any) -> NoReturn:
            raise AuthorizationError

        @api.get("/authentication-error", auth=lambda _: None)
        def authentication_error(*_: Any) -> str:
            return "Secret"

        return [path("", api.urls)]

    def test_exception(self, api_client: Client) -> None:
        response = api_client.get("/exception")
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json() == {
            "message": "An unexpected error has occurred.",
        }

    def test_404(self, api_client: Client) -> None:
        response = api_client.get("/404")
        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {
            "message": "The requested resource could not be found.",
        }

    def test_http_error(self, api_client: Client) -> None:
        response = api_client.get("/http-error")
        assert response.status_code == HTTPStatus.IM_A_TEAPOT
        assert response.json() == {
            "message": "Something went wrong.",
        }

    def test_validation_error(self, api_client: Client) -> None:
        response = api_client.post("/validation-error", data={"foo": "foo"})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json() == {
            "message": "Invalid payload.",
            "details": [
                {
                    "type": "missing",
                    "loc": ["body", "payload", "bar"],
                    "msg": "Field required",
                },
            ],
        }

    def test_authorization_error(self, api_client: Client) -> None:
        response = api_client.get("/authorization-error")
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {
            "message": "You are not allowed to perform this action.",
        }

    def test_authentication_error(self, api_client: Client) -> None:
        response = api_client.get("/authentication-error")
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"message": "Authentication failed or missing."}
