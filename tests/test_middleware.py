from unittest.mock import AsyncMock, MagicMock

from django.conf import LazySettings
from django.http import HttpResponse
from django.test import RequestFactory
from pytest_mock import MockerFixture

from app.middleware import HttpRequest, request_meta_middleware


def _apply_sync(
    rf: RequestFactory,
    **meta: str,
) -> tuple[HttpResponse, MagicMock]:
    request = rf.get("/", **meta)  # type: ignore[arg-type]
    inner = MagicMock(return_value=HttpResponse("ok"))
    middleware = request_meta_middleware(inner)
    response = middleware(request)
    return response, inner


async def _apply_async(
    rf: RequestFactory,
    **meta: str,
) -> tuple[HttpResponse, AsyncMock]:
    request = rf.get("/", **meta)  # type: ignore[arg-type]
    inner = AsyncMock(return_value=HttpResponse("ok"))
    middleware = request_meta_middleware(inner)
    response = await middleware(request)
    return response, inner


def _get_enriched_request(rf: RequestFactory, **meta: str) -> HttpRequest:
    _, inner = _apply_sync(rf, **meta)
    return inner.call_args[0][0]  # type: ignore[no-any-return]


def assert_is_uuid_hex(value: str) -> None:
    assert len(value) == 32
    assert all(c in "0123456789abcdef" for c in value)


class TestRequestIdFromHeader:
    def test_uses_header_value(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID="abc-123")
        assert request.request_id == "abc-123"

    def test_sanitizes_illegal_characters(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID="valid<>chars!here")
        assert request.request_id == "validcharshere"

    def test_strips_non_ascii_characters(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID="abc-d\u00e9fg\u200b")
        assert request.request_id == "abc-dfg"

    def test_truncates_long_values(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        long_id = "a" * 200
        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID=long_id)
        assert request.request_id == "a" * 64

    def test_falls_back_to_uuid_when_header_all_illegal(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID="<>!@#$")
        assert_is_uuid_hex(request.request_id)

    def test_falls_back_to_uuid_when_header_missing(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        request = _get_enriched_request(rf)
        assert_is_uuid_hex(request.request_id)


class TestRequestIdFallback:
    def test_proxy_disabled(self, rf: RequestFactory, settings: LazySettings) -> None:
        settings.TRUSTED_PROXY = False
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID="from-proxy")
        assert_is_uuid_hex(request.request_id)

    def test_no_header_name_configured(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = ""

        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID="from-proxy")
        assert_is_uuid_hex(request.request_id)


class TestClientIp:
    def test_forwards_proxy_count(
        self,
        mocker: MockerFixture,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_COUNT = 2
        settings.REVERSE_PROXY_IP_HEADERS = []

        mock_get_ip = mocker.patch(
            "app.middleware.get_client_ip",
            return_value=("198.51.100.1", True),
        )
        request = _get_enriched_request(rf)

        assert request.client_ip == "198.51.100.1"
        mock_get_ip.assert_called_once()
        _, kwargs = mock_get_ip.call_args
        assert kwargs["proxy_count"] == 2
        assert "request_header_order" not in kwargs

    def test_forwards_ip_headers(
        self,
        mocker: MockerFixture,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_COUNT = 2
        headers = ["CF-Connecting-IP", "X-Forwarded-For"]
        settings.REVERSE_PROXY_IP_HEADERS = headers

        mock_get_ip = mocker.patch(
            "app.middleware.get_client_ip",
            return_value=("198.51.100.2", True),
        )
        request = _get_enriched_request(rf)

        assert request.client_ip == "198.51.100.2"
        _, kwargs = mock_get_ip.call_args
        assert kwargs["request_header_order"] == headers

    def test_untrusted_proxy_ignores_configured_headers(
        self,
        mocker: MockerFixture,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = False
        settings.REVERSE_PROXY_COUNT = 2
        settings.REVERSE_PROXY_IP_HEADERS = ["CF-Connecting-IP"]

        mock_get_ip = mocker.patch(
            "app.middleware.get_client_ip",
            return_value=("198.51.100.3", True),
        )
        request = _get_enriched_request(rf)

        assert request.client_ip == "198.51.100.3"
        _, kwargs = mock_get_ip.call_args
        assert kwargs["request_header_order"] == ("REMOTE_ADDR",)
        assert "proxy_count" not in kwargs

    def test_untrusted_proxy_rejects_forged_forwarding_header(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = False

        request = _get_enriched_request(
            rf,
            HTTP_X_FORWARDED_FOR="9.9.9.9",
            REMOTE_ADDR="203.0.113.7",
        )

        assert request.client_ip == "203.0.113.7"


class TestSentryIntegration:
    def test_sets_sentry_tag(
        self,
        mocker: MockerFixture,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        mock_set_tag = mocker.patch("app.middleware.sentry_sdk.set_tag")
        request = _get_enriched_request(rf, HTTP_X_REQUEST_ID="sentry-test-id")

        mock_set_tag.assert_called_once_with("request_id", "sentry-test-id")
        assert request.request_id == "sentry-test-id"


class TestAsyncPath:
    async def test_enriches_request(
        self,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        response, inner = await _apply_async(rf, HTTP_X_REQUEST_ID="async-id")
        request = inner.call_args[0][0]

        assert response.status_code == 200
        assert request.request_id == "async-id"
        assert hasattr(request, "client_ip")


class TestLoggerContextualization:
    def test_sync_context(
        self,
        mocker: MockerFixture,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        mock_ctx = mocker.patch("app.middleware.logger.contextualize")
        _get_enriched_request(rf, HTTP_X_REQUEST_ID="ctx-id")

        mock_ctx.assert_called_once_with(request_id="ctx-id", client_ip=mocker.ANY)

    async def test_async_context(
        self,
        mocker: MockerFixture,
        rf: RequestFactory,
        settings: LazySettings,
    ) -> None:
        settings.TRUSTED_PROXY = True
        settings.REVERSE_PROXY_REQUEST_ID_HEADER = "X-Request-ID"

        mock_ctx = mocker.patch("app.middleware.logger.contextualize")
        await _apply_async(rf, HTTP_X_REQUEST_ID="ctx-id")

        mock_ctx.assert_called_once_with(request_id="ctx-id", client_ip=mocker.ANY)
