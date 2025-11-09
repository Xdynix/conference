from typing import Any

import pytest
from django.test import Client
from django.urls import path
from ninja import NinjaAPI, Schema
from ninja.pagination import paginate

from app.core.models import User
from app.ninja.pagination import CursorPagination
from tests.base import URLConfTestCase, URLPatterns


async def create_users(usernames: list[str]) -> list[User]:
    users: list[User] = []
    for username in usernames:
        users.append(
            await User.objects.acreate(
                username=username,
                email=f"{username}@example.com",
            )
        )
    return users


@pytest.mark.django_db(transaction=True)
class TestCursorPagination:
    async def test_descending_pagination_sets_next_token(self) -> None:
        await create_users(["alpha", "bravo", "charlie", "delta"])
        paginator = CursorPagination[User, str](cursor_field="username")
        pagination = CursorPagination.Input[str](page_size=2, order="desc")

        result = await paginator.apaginate_queryset(User.objects.all(), pagination)

        usernames = [user.username for user in result["items"]]
        assert usernames == ["delta", "charlie"]
        assert result["next_page_token"] == "charlie"

    async def test_ascending_pagination_sets_next_token(self) -> None:
        await create_users(["alpha", "bravo", "charlie", "delta"])
        paginator = CursorPagination[User, str](cursor_field="username")
        pagination = CursorPagination.Input[str](page_size=2, order="asc")

        result = await paginator.apaginate_queryset(User.objects.all(), pagination)

        usernames = [user.username for user in result["items"]]
        assert usernames == ["alpha", "bravo"]
        assert result["next_page_token"] == "bravo"

    async def test_descending_pagination_respects_page_token(self) -> None:
        await create_users(["alpha", "bravo", "charlie", "delta"])
        paginator = CursorPagination[User, str](cursor_field="username")
        pagination = CursorPagination.Input[str](
            page_size=1,
            order="desc",
            page_token="charlie",  # noqa: S106
        )

        result = await paginator.apaginate_queryset(User.objects.all(), pagination)

        usernames = [user.username for user in result["items"]]
        assert usernames == ["bravo"]
        assert result["next_page_token"] == "bravo"

    async def test_ascending_pagination_respects_page_token(self) -> None:
        await create_users(["alpha", "bravo", "charlie", "delta"])
        paginator = CursorPagination[User, str](cursor_field="username")
        pagination = CursorPagination.Input[str](
            page_size=1,
            order="asc",
            page_token="bravo",  # noqa: S106
        )

        result = await paginator.apaginate_queryset(User.objects.all(), pagination)

        usernames = [user.username for user in result["items"]]
        assert usernames == ["charlie"]
        assert result["next_page_token"] == "charlie"

    async def test_last_page_returns_no_next_token(self) -> None:
        await create_users(["alpha", "bravo"])
        paginator = CursorPagination[User, str](cursor_field="username")
        pagination = CursorPagination.Input[str](page_size=5, order="desc")

        result = await paginator.apaginate_queryset(User.objects.all(), pagination)

        usernames = [user.username for user in result["items"]]
        assert usernames == ["bravo", "alpha"]
        assert result["next_page_token"] is None

    async def test_warns_when_queryset_is_ordered(self) -> None:
        await create_users(["alpha", "bravo"])
        paginator = CursorPagination[User, str](cursor_field="username")
        pagination = CursorPagination.Input[str](page_size=1, order="asc")

        queryset = User.objects.order_by("date_joined")
        with pytest.warns(UserWarning):
            await paginator.apaginate_queryset(queryset, pagination)


@pytest.mark.django_db
class TestCursorPaginationAPIIntegration(URLConfTestCase):
    path = "/users"

    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        class UserSchema(Schema):
            username: str

        @api.get(self.path, response=list[UserSchema])
        @paginate(CursorPagination, cursor_field="username")
        async def list_users(*_: Any) -> Any:
            return User.objects.all()

        return [path("", api.urls)]

    @pytest.fixture(autouse=True)
    def users(self) -> None:
        for username in ["alpha", "bravo", "charlie"]:
            User.objects.create_user(username=username)

    def test_endpoint_returns_paginated_payload(self, api_client: Client) -> None:
        response = api_client.get(self.path, {"page_size": 2})
        assert response.status_code == 200

        payload = response.json()
        assert payload["items"] == [
            {"username": "charlie"},
            {"username": "bravo"},
        ]
        assert payload["next_page_token"] == "bravo"

    def test_endpoint_respects_query_parameters(self, api_client: Client) -> None:
        response = api_client.get(
            self.path,
            query_params={
                "order": "asc",
                "page_size": 1,
                "page_token": "bravo",
            },
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["items"] == [{"username": "charlie"}]
        assert payload["next_page_token"] is None

    def test_endpoint_supports_iterating_pages(self, api_client: Client) -> None:
        all_items: list[dict[str, str]] = []
        page_counts: list[int] = []

        next_token: str | None = None
        while True:
            query_params: dict[str, Any] = {"page_size": 2}
            if next_token is not None:
                query_params["page_token"] = next_token

            response = api_client.get(self.path, query_params=query_params)
            assert response.status_code == 200

            payload = response.json()
            items = payload["items"]
            all_items.extend(items)
            page_counts.append(len(items))
            next_token = payload["next_page_token"]
            if next_token is None:
                break

        assert all_items == [
            {"username": "charlie"},
            {"username": "bravo"},
            {"username": "alpha"},
        ]
        assert page_counts == [2, 1]
