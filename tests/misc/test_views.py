from django.test import Client


def test_favicon(client: Client) -> None:
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response["content-type"] == "image/svg+xml"
