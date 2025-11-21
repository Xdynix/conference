from http import HTTPStatus

from django.test import Client
from django.urls import reverse

from tests.helpers import any_str, approx_now


def test_get_health_status(api_client: Client) -> None:
    response = api_client.get(reverse("api-1.0.0:get-health-status"))
    assert response.status_code == HTTPStatus.OK

    assert response.json() == {
        "now": approx_now(),
        "client_ip": any_str,
    }
    assert "no-cache" in response.headers["Cache-Control"]
