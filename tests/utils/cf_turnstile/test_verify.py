from uuid import uuid4

import httpx
import orjson
import pytest
from django.conf import LazySettings
from respx.router import MockRouter

from app.utils.cf_turnstile.verify import verify_cf_turnstile_response

DEFAULT_CF_TURNSTILE_VERIFY_URL = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)


class TestVerifyCfTurnstileResponse:
    async def test_successful_verification(
        self,
        settings: LazySettings,
        respx_mock: MockRouter,
    ) -> None:
        settings.CF_TURNSTILE_SECRET_KEY = "test-secret"
        response_data = {
            "success": True,
            "challenge_ts": "2000-01-01T00:00:00.000Z",
        }
        mock_verify = respx_mock.post(DEFAULT_CF_TURNSTILE_VERIFY_URL).mock(
            return_value=httpx.Response(200, json=response_data)
        )
        cf_turnstile_response = "test-response"

        success, data = await verify_cf_turnstile_response(cf_turnstile_response)

        assert success is True
        assert data == response_data

        assert mock_verify.call_count == 1
        assert orjson.loads(mock_verify.calls.last.request.content) == {
            "secret": "test-secret",
            "response": cf_turnstile_response,
        }

    async def test_failed_verification(self, respx_mock: MockRouter) -> None:
        response_data = {"success": False, "error-codes": ["invalid-input-response"]}
        mock_verify = respx_mock.post(DEFAULT_CF_TURNSTILE_VERIFY_URL).mock(
            return_value=httpx.Response(200, json=response_data)
        )
        cf_turnstile_response = "invalid-response"

        success, data = await verify_cf_turnstile_response(cf_turnstile_response)

        assert success is False
        assert data == response_data
        assert mock_verify.call_count == 1

    async def test_verification_with_optional_parameters(
        self,
        settings: LazySettings,
        respx_mock: MockRouter,
    ) -> None:
        settings.CF_TURNSTILE_SECRET_KEY = "test-secret"
        response_data = {"success": True}
        mock_verify = respx_mock.post(DEFAULT_CF_TURNSTILE_VERIFY_URL).mock(
            return_value=httpx.Response(200, json=response_data)
        )
        cf_turnstile_response = "test-response"
        remote_ip = "192.168.1.1"
        idempotency_key = uuid4()

        success, data = await verify_cf_turnstile_response(
            cf_turnstile_response,
            remote_ip=remote_ip,
            idempotency_key=idempotency_key,
        )

        assert success is True

        assert mock_verify.call_count == 1
        assert orjson.loads(mock_verify.calls.last.request.content) == {
            "secret": "test-secret",
            "response": cf_turnstile_response,
            "remoteip": remote_ip,
            "idempotency_key": str(idempotency_key),
        }

    async def test_verification_with_custom_secret_and_url(
        self,
        respx_mock: MockRouter,
    ) -> None:
        custom_secret = "custom-secret-key"
        custom_url = "https://custom.verify.url/"
        response_data = {"success": True}
        mock_verify = respx_mock.post(custom_url).mock(
            return_value=httpx.Response(200, json=response_data)
        )
        cf_turnstile_response = "test-response"

        success, data = await verify_cf_turnstile_response(
            cf_turnstile_response,
            secret_key=custom_secret,
            verify_url=custom_url,
        )

        assert success is True
        assert data == response_data

        assert mock_verify.call_count == 1
        request = mock_verify.calls.last.request
        assert request.url == custom_url
        assert orjson.loads(request.content)["secret"] == custom_secret

    async def test_http_error_handling(self, respx_mock: MockRouter) -> None:
        respx_mock.post(DEFAULT_CF_TURNSTILE_VERIFY_URL).mock(
            return_value=httpx.Response(500)
        )
        cf_turnstile_response = "test-response"

        with pytest.raises(httpx.HTTPStatusError):
            await verify_cf_turnstile_response(cf_turnstile_response)

    async def test_timeout_handling(self, respx_mock: MockRouter) -> None:
        respx_mock.post(DEFAULT_CF_TURNSTILE_VERIFY_URL).mock(
            side_effect=httpx.TimeoutException
        )
        cf_turnstile_response = "test-response"

        with pytest.raises(httpx.TimeoutException):
            await verify_cf_turnstile_response(cf_turnstile_response)

    async def test_missing_success_field_in_response(
        self,
        respx_mock: MockRouter,
    ) -> None:
        response_data = {"error-codes": ["internal-error"]}
        mock_verify = respx_mock.post(DEFAULT_CF_TURNSTILE_VERIFY_URL).mock(
            return_value=httpx.Response(200, json=response_data)
        )
        cf_turnstile_response = "test-response"

        success, data = await verify_cf_turnstile_response(cf_turnstile_response)

        assert success is False
        assert data == response_data
        assert mock_verify.call_count == 1

    async def test_settings_default_values(
        self,
        settings: LazySettings,
        respx_mock: MockRouter,
    ) -> None:
        settings.CF_TURNSTILE_SECRET_KEY = "test-secret"
        settings.CF_TURNSTILE_VERIFY_URL = "https://test.verify.url/"
        response_data = {"success": True}
        mock_verify = respx_mock.post("https://test.verify.url/").mock(
            return_value=httpx.Response(200, json=response_data)
        )
        cf_turnstile_response = "test-response"

        success, data = await verify_cf_turnstile_response(cf_turnstile_response)

        assert success is True

        assert mock_verify.call_count == 1
        request = mock_verify.calls.last.request
        assert request.url == "https://test.verify.url/"
        assert orjson.loads(request.content)["secret"] == "test-secret"


class TestVerifyCfTurnstileResponseE2E:
    async def test_always_pass_secret_key(self, settings: LazySettings) -> None:
        settings.CF_TURNSTILE_SECRET_KEY = "1x0000000000000000000000000000000AA"
        cf_turnstile_response = "XXXX.DUMMY.TOKEN.XXXX"

        success, data = await verify_cf_turnstile_response(cf_turnstile_response)

        assert success is True
        assert "success" in data
        assert data["success"] is True

    async def test_always_fail_secret_key(self, settings: LazySettings) -> None:
        settings.CF_TURNSTILE_SECRET_KEY = "2x0000000000000000000000000000000AA"
        cf_turnstile_response = "XXXX.DUMMY.TOKEN.XXXX"

        success, data = await verify_cf_turnstile_response(cf_turnstile_response)

        assert success is False
        assert "success" in data
        assert data["success"] is False
        assert data["error-codes"]

    async def test_response_already_spent_error(self, settings: LazySettings) -> None:
        settings.CF_TURNSTILE_SECRET_KEY = "3x0000000000000000000000000000000AA"
        cf_turnstile_response = "XXXX.DUMMY.TOKEN.XXXX"

        success, data = await verify_cf_turnstile_response(cf_turnstile_response)

        assert success is False
        assert "success" in data
        assert data["success"] is False
        assert "error-codes" in data
        assert "timeout-or-duplicate" in data["error-codes"]
