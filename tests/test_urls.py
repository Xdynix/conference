from django.urls import reverse


def test_admin_site() -> None:
    assert reverse("admin:index")
