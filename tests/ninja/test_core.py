from http import HTTPStatus
from typing import Any
from uuid import uuid4

import pytest
from django.conf import LazySettings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import path, reverse
from faker.proxy import Faker
from ninja import NinjaAPI, Schema
from pytest_mock import MockerFixture

from app.ninja.core import AppNinjaAPI
from app.utils.orjson import serializer
from tests.base import URLConfTestCase, URLPatterns

User = get_user_model()


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


class TestDocsDecoratorDebug(URLConfTestCase):
    @pytest.fixture
    def api(self, settings: LazySettings) -> AppNinjaAPI:
        settings.DEBUG = True
        return AppNinjaAPI.build(urls_namespace=uuid4().hex)

    @pytest.fixture
    def urlpatterns(self, api: AppNinjaAPI) -> URLPatterns:
        return [path("", api.urls)]

    def test_docs_open_in_debug(self, client: Client, api: AppNinjaAPI) -> None:
        response = client.get(reverse(f"{api.urls_namespace}:openapi-view"))
        assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
class TestDocsDecoratorLocked(URLConfTestCase):
    @pytest.fixture
    def api(self, settings: LazySettings) -> AppNinjaAPI:
        settings.DEBUG = False
        return AppNinjaAPI.build(urls_namespace=uuid4().hex)

    @pytest.fixture
    def urlpatterns(self, api: AppNinjaAPI) -> URLPatterns:
        return [path("", api.urls)]

    def test_docs_forbidden_for_anonymous(
        self,
        client: Client,
        api: AppNinjaAPI,
    ) -> None:
        response = client.get(reverse(f"{api.urls_namespace}:openapi-view"))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_docs_allowed_for_superuser(
        self,
        faker: Faker,
        client: Client,
        api: AppNinjaAPI,
    ) -> None:
        user = User.objects.create_superuser(username=faker.user_name())
        client.force_login(user)

        response = client.get(reverse(f"{api.urls_namespace}:openapi-view"))
        assert response.status_code == HTTPStatus.OK
