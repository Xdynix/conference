import pytest
from django.db import IntegrityError
from faker import Faker

from app.core.models import Permission, User
from tests.data import (
    EMAIL_NORMALIZATION_DATA,
    USERNAME_NORMALIZATION_DATA,
)


@pytest.mark.parametrize(
    "username, expected",
    USERNAME_NORMALIZATION_DATA,
)
def test_normalize_username(username: str | None, expected: str) -> None:
    assert User.normalize_username(username) == expected


@pytest.mark.parametrize(
    "email, expected",
    EMAIL_NORMALIZATION_DATA,
)
def test_normalize_email(email: str | None, expected: str) -> None:
    assert User.objects.normalize_email(email) == expected


@pytest.mark.django_db
class TestUser:
    def test_unique_email(self, faker: Faker) -> None:
        email = faker.email()
        with pytest.raises(IntegrityError):
            User.objects.bulk_create(
                [
                    User(username=faker.user_name(), email=email),
                    User(username=faker.user_name(), email=email),
                ]
            )

    def test_unique_email_allow_blank(self, faker: Faker) -> None:
        User.objects.bulk_create(
            [
                User(username=faker.user_name()),
                User(username=faker.user_name()),
            ]
        )

    def test_given_name_property(self, faker: Faker) -> None:
        user = User()
        first_name = faker.first_name()
        user.first_name = first_name
        assert user.given_name == first_name

    def test_given_name_setter(self, faker: Faker) -> None:
        user = User()
        given_name = faker.first_name()
        user.given_name = given_name
        assert user.first_name == given_name

    def test_family_name_property(self, faker: Faker) -> None:
        user = User()
        last_name = faker.last_name()
        user.last_name = last_name
        assert user.family_name == last_name

    def test_family_name_setter(self, faker: Faker) -> None:
        user = User()
        family_name = faker.last_name()
        user.family_name = family_name
        assert user.last_name == family_name


class TestPermission:
    def test_str(self) -> None:
        assert str(Permission(key="foobar")) == "foobar"
