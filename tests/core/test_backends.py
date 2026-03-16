import pytest
from faker import Faker

from app.core.backends import EmailOrUsernameBackend
from app.core.models import User
from tests.helpers import a_update_object, update_object


@pytest.fixture
def backend() -> EmailOrUsernameBackend:
    return EmailOrUsernameBackend()


@pytest.fixture
def password(faker: Faker) -> str:
    return faker.password()


@pytest.fixture
def user(faker: Faker, password: str) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        email=faker.email(),
        password=password,
    )


@pytest.mark.django_db
class TestAuthenticate:
    def test_with_username(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        result = backend.authenticate(None, username=user.username, password=password)
        assert result == user

    def test_with_email(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        result = backend.authenticate(None, username=user.email, password=password)
        assert result == user

    def test_email_case_insensitive(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        result = backend.authenticate(
            None,
            username=user.email.swapcase(),
            password=password,
        )
        assert result == user

    def test_wrong_password(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
    ) -> None:
        result = backend.authenticate(
            None,
            username=user.username,
            password="wrong",  # noqa: S106
        )
        assert result is None

    def test_nonexistent_username(
        self,
        backend: EmailOrUsernameBackend,
        faker: Faker,
    ) -> None:
        result = backend.authenticate(
            None,
            username=faker.user_name(),
            password="whatever",  # noqa: S106
        )
        assert result is None

    def test_nonexistent_email(
        self,
        backend: EmailOrUsernameBackend,
        faker: Faker,
    ) -> None:
        result = backend.authenticate(
            None,
            username=faker.email(),
            password="whatever",  # noqa: S106
        )
        assert result is None

    def test_inactive_user(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        update_object(user, is_active=False)
        result = backend.authenticate(None, username=user.username, password=password)
        assert result is None

    def test_none_username(self, backend: EmailOrUsernameBackend) -> None:
        assert (
            backend.authenticate(
                None,
                username=None,
                password="whatever",  # noqa: S106
            )
            is None
        )

    def test_none_password(
        self,
        backend: EmailOrUsernameBackend,
        faker: Faker,
    ) -> None:
        assert (
            backend.authenticate(None, username=faker.user_name(), password=None)
            is None
        )


@pytest.mark.django_db(transaction=True)
class TestAauthenticate:
    async def test_with_username(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        result = await backend.aauthenticate(
            None,
            username=user.username,
            password=password,
        )
        assert result == user

    async def test_with_email(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        result = await backend.aauthenticate(
            None,
            username=user.email,
            password=password,
        )
        assert result == user

    async def test_email_case_insensitive(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        result = await backend.aauthenticate(
            None,
            username=user.email.swapcase(),
            password=password,
        )
        assert result == user

    async def test_wrong_password(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
    ) -> None:
        result = await backend.aauthenticate(
            None,
            username=user.username,
            password="wrong",  # noqa: S106
        )
        assert result is None

    async def test_nonexistent_username(
        self,
        backend: EmailOrUsernameBackend,
        faker: Faker,
    ) -> None:
        result = await backend.aauthenticate(
            None,
            username=faker.user_name(),
            password="whatever",  # noqa: S106
        )
        assert result is None

    async def test_nonexistent_email(
        self,
        backend: EmailOrUsernameBackend,
        faker: Faker,
    ) -> None:
        result = await backend.aauthenticate(
            None,
            username=faker.email(),
            password="whatever",  # noqa: S106
        )
        assert result is None

    async def test_inactive_user(
        self,
        backend: EmailOrUsernameBackend,
        user: User,
        password: str,
    ) -> None:
        await a_update_object(user, is_active=False)
        result = await backend.aauthenticate(
            None,
            username=user.username,
            password=password,
        )
        assert result is None

    async def test_none_username(self, backend: EmailOrUsernameBackend) -> None:
        assert (
            await backend.aauthenticate(
                None,
                username=None,
                password="whatever",  # noqa: S106
            )
            is None
        )

    async def test_none_password(
        self,
        backend: EmailOrUsernameBackend,
        faker: Faker,
    ) -> None:
        assert (
            await backend.aauthenticate(None, username=faker.user_name(), password=None)
            is None
        )
