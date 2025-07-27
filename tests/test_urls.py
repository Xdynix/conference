from django.urls import reverse


def test_admin_site() -> None:
    assert reverse("admin:index")


def test_openapi_doc() -> None:
    assert reverse("api-1.0.0:openapi-view")
    assert reverse("api-1.0.0:openapi-json")
