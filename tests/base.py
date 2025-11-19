from abc import ABCMeta, abstractmethod
from collections.abc import Iterable, Iterator
from http import HTTPStatus
from importlib import import_module
from typing import Any

import pytest
from django.conf import LazySettings
from django.urls.resolvers import URLPattern, URLResolver

from tests.helpers import any_str


class ResponseAssertionsMixin:
    """Common helpers for asserting API-style HTTP responses."""

    @classmethod
    def assert_response_is_ok(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.OK
        assert response.json() == "OK"

    @classmethod
    def assert_response_is_forbidden(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"message": any_str}

    @classmethod
    def assert_response_is_unauthorized(cls, response: Any) -> None:
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"message": any_str}


URLPatterns = Iterable[URLResolver | URLPattern]


class URLConfTestCase(metaclass=ABCMeta):
    """Base class for test cases that require overriding the URL configuration."""

    @pytest.fixture
    @abstractmethod
    def urlpatterns(self, *_: Any, **__: Any) -> URLPatterns:
        raise NotImplementedError

    @pytest.fixture(autouse=True)
    def override_urlconf(
        self,
        settings: LazySettings,
        urlpatterns: URLPatterns,
    ) -> Iterator[None]:
        settings.ROOT_URLCONF = self.__module__

        module = import_module(self.__module__)
        original_urlpatterns = getattr(module, "urlpatterns", None)
        module.urlpatterns = urlpatterns  # type: ignore[attr-defined]

        yield

        if original_urlpatterns is not None:
            module.urlpatterns = original_urlpatterns  # type: ignore[attr-defined]
        else:
            del module.urlpatterns
