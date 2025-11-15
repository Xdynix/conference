import pytest
from django.db import IntegrityError
from django.utils import timezone
from faker import Faker

from app.core.models import GlobalRole, GlobalRoleAssignment, PasswordResetToken, User
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


class TestGlobalRoleAssignment:
    def test_str(self) -> None:
        user = User(username="user")
        role = GlobalRole.ADMIN
        assignment = GlobalRoleAssignment(user=user, role=role)
        assert str(assignment) == "Admin: user"


@pytest.mark.django_db
class TestPasswordResetToken:
    def test_str_pending(self, faker: Faker) -> None:
        username = faker.user_name()
        user = User.objects.create_user(username=username)
        token = PasswordResetToken(
            user=user,
            token_hash="",
        )
        assert str(token) == f"{username} (pending)"

    def test_str_consumed(self, faker: Faker) -> None:
        username = faker.user_name()
        user = User.objects.create_user(username=username)
        token = PasswordResetToken(
            user=user,
            token_hash="",
            consume_time=timezone.now(),
        )
        assert str(token) == f"{username} (consumed)"
