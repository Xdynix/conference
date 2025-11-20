from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from app.conference.models import Keyword, KeywordSet


@pytest.mark.django_db
def test_list_keyword_sets(api_client: Client) -> None:
    innovation = KeywordSet.objects.create(name="Innovation")
    innovation.keywords.set(
        [
            Keyword.objects.create(text="ai"),
            Keyword.objects.create(text="cloud"),
        ],
    )
    defense = KeywordSet.objects.create(name="Defense")
    defense.keywords.set(
        [
            Keyword.objects.create(text="security"),
        ],
    )

    response = api_client.get(reverse("api-1.0.0:list-keyword-sets"))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == [
        {
            "name": "Defense",
            "keywords": ["security"],
        },
        {
            "name": "Innovation",
            "keywords": ["ai", "cloud"],
        },
    ]
