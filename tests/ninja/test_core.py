from typing import Any

import pytest
from django.test import Client
from django.urls import path, reverse
from ninja import NinjaAPI, Schema
from pytest_mock import MockerFixture

from app.utils.orjson import serializer
from tests.base import URLConfTestCase, URLPatterns


class TestAppNinjaAPI(URLConfTestCase):
    path = "/foobar"

    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        class Foobar(Schema):
            foobar: str

        @api.post(self.path, response=Foobar)
        def echo_foobar(*_: Any, payload: Foobar) -> Foobar:
            return payload

        return [path("", api.urls)]

    def test_openapi_operation_id(self, api: NinjaAPI) -> None:
        schema = api.get_openapi_schema()
        operation = schema["paths"][self.path]["post"]
        assert operation["operationId"] == "echo-foobar"

    def test_get_operation_url_name(self, api: NinjaAPI) -> None:
        assert reverse(f"{api.urls_namespace}:echo-foobar") == "/foobar"

    def test_json(self, mocker: MockerFixture, api_client: Client) -> None:
        dumps_spy = mocker.spy(serializer, "dumps")
        loads_spy = mocker.spy(serializer, "loads")

        payload = {"foobar": "foobar"}
        response = api_client.post("/foobar", data=payload)
        assert response.json() == payload

        dumps_spy.assert_called_once()
        loads_spy.assert_called_once()
