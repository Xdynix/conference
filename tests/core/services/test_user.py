from typing import Any
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from faker import Faker
from pytest_mock import MockerFixture

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.core.services.user import InvalidPassword, UserIdentityConflict, UserService


@pytest.mark.django_db(transaction=True)
class TestUserServiceCreateUser:
    @pytest.fixture
    def mock_dispatch(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("app.core.services.user.create_user_registry.dispatch")

    @pytest.mark.parametrize("managed", [True, False])
    def test_happy_path(
        self,
        faker: Faker,
        mock_dispatch: MagicMock,
        managed: bool,
    ) -> None:
        username = faker.user_name()
        email = faker.email()
        password = faker.password()
        payload: dict[str, Any] = {"key": "value"}

        user = UserService.create_user(
            username=username,
            email=email,
            password=password,
            managed=managed,
            payload=payload,
        )

        db_user = User.objects.get(pk=user.pk)
        assert user.username == db_user.username == username
        assert user.email == db_user.email == email
        assert user.check_password(password)
        assert db_user.check_password(password)
        assert user.managed == db_user.managed == managed
        mock_dispatch.assert_called_once_with(user, payload)

    def test_raises_invalid_password_for_weak_password(
        self,
        mocker: MockerFixture,
        faker: Faker,
        mock_dispatch: MagicMock,
    ) -> None:
        mocker.patch(
            "app.core.services.user.validate_password",
            side_effect=ValidationError(["Password too weak."]),
        )

        with pytest.raises(InvalidPassword) as exc_info:
            UserService.create_user(
                username=faker.user_name(),
                email=faker.email(),
                password=faker.password(),
                managed=False,
                payload={},
            )

        assert exc_info.value.messages == ["Password too weak."]
        assert User.objects.count() == 0
        mock_dispatch.assert_not_called()

    def test_raises_user_identity_conflict_for_duplicate_username(
        self,
        faker: Faker,
        mock_dispatch: MagicMock,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

        with pytest.raises(UserIdentityConflict):
            UserService.create_user(
                username=existing_user.username,
                email=faker.email(),
                password=faker.password(),
                managed=False,
                payload={},
            )

        assert User.objects.filter(username=existing_user.username).count() == 1
        mock_dispatch.assert_not_called()

    def test_raises_user_identity_conflict_for_duplicate_email(
        self,
        faker: Faker,
        mock_dispatch: MagicMock,
    ) -> None:
        existing_user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

        with pytest.raises(UserIdentityConflict):
            UserService.create_user(
                username=faker.user_name(),
                email=existing_user.email,
                password=faker.password(),
                managed=False,
                payload={},
            )

        assert User.objects.filter(email=existing_user.email).count() == 1
        mock_dispatch.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestUserServiceUpdateUser:
    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    async def test_update_username_only(self, faker: Faker, user: User) -> None:
        new_username = faker.user_name()
        original_email = user.email

        updated = await UserService.update_user(user=user, username=new_username)

        db_updated = await User.objects.aget(pk=updated.pk)
        assert updated.username == db_updated.username == new_username
        assert updated.email == db_updated.email == original_email
        await user.arefresh_from_db()

    async def test_update_email_only(self, faker: Faker, user: User) -> None:
        original_username = user.username
        new_email = faker.email()

        updated = await UserService.update_user(user=user, email=new_email)

        db_updated = await User.objects.aget(pk=updated.pk)
        assert updated.username == db_updated.username == original_username
        assert updated.email == db_updated.email == new_email

    async def test_update_both_username_and_email(
        self, faker: Faker, user: User
    ) -> None:
        new_username = faker.user_name()
        new_email = faker.email()

        updated = await UserService.update_user(
            user=user,
            username=new_username,
            email=new_email,
        )

        db_updated = await User.objects.aget(pk=updated.pk)
        assert updated.username == db_updated.username == new_username
        assert updated.email == db_updated.email == new_email

    async def test_no_op_when_both_none(self, user: User) -> None:
        original_username = user.username
        original_email = user.email

        updated = await UserService.update_user(user=user)

        db_updated = await User.objects.aget(pk=updated.pk)
        assert updated.username == db_updated.username == original_username
        assert updated.email == db_updated.email == original_email

    async def test_raises_user_identity_conflict_for_duplicate_username(
        self,
        faker: Faker,
    ) -> None:
        existing_user = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        user = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_username = user.username

        with pytest.raises(UserIdentityConflict):
            await UserService.update_user(user=user, username=existing_user.username)

        await user.arefresh_from_db()
        assert user.username == original_username

    async def test_raises_user_identity_conflict_for_duplicate_email(
        self,
        faker: Faker,
    ) -> None:
        existing_user = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        user = await User.objects.acreate_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        original_email = user.email

        with pytest.raises(UserIdentityConflict):
            await UserService.update_user(user=user, email=existing_user.email)

        await user.arefresh_from_db()
        assert user.email == original_email


@pytest.mark.django_db(transaction=True)
class TestUserServiceUpdatePassword:
    @pytest.fixture
    def old_password(self) -> str:
        return "OldPassword123!"

    @pytest.fixture
    def user(self, faker: Faker, old_password: str) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            password=old_password,
        )

    async def test_happy_path(
        self,
        faker: Faker,
        old_password: str,
        user: User,
    ) -> None:
        new_password = faker.password()

        await UserService.update_password(user=user, new_password=new_password)

        await user.arefresh_from_db()
        assert not await user.acheck_password(old_password)
        assert await user.acheck_password(new_password)

    async def test_raises_invalid_password_for_weak_password(
        self,
        mocker: MockerFixture,
        faker: Faker,
        old_password: str,
        user: User,
    ) -> None:
        mocker.patch(
            "app.core.services.user.validate_password",
            side_effect=ValidationError(["Password too weak.", "Password too common."]),
        )

        with pytest.raises(InvalidPassword) as exc_info:
            await UserService.update_password(user=user, new_password=faker.password())

        assert exc_info.value.messages == ["Password too weak.", "Password too common."]
        await user.arefresh_from_db()
        assert await user.acheck_password(old_password)


@pytest.mark.django_db(transaction=True)
class TestUserServiceChangePassword:
    @pytest.fixture
    def old_password(self) -> str:
        return "OldPassword123!"

    @pytest.fixture
    def user(self, faker: Faker, old_password: str) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            password=old_password,
        )

    async def test_happy_path(
        self,
        faker: Faker,
        old_password: str,
        user: User,
    ) -> None:
        new_password = faker.password()

        await UserService.change_password(
            user=user,
            old_password=old_password,
            new_password=new_password,
        )

        await user.arefresh_from_db()
        assert not await user.acheck_password(old_password)
        assert await user.acheck_password(new_password)

    async def test_raises_value_error_for_incorrect_old_password(
        self,
        faker: Faker,
        old_password: str,
        user: User,
    ) -> None:
        with pytest.raises(ValueError, match="Invalid old password"):
            await UserService.change_password(
                user=user,
                old_password=faker.password(),
                new_password=faker.password(),
            )

        await user.arefresh_from_db()
        assert await user.acheck_password(old_password)

    async def test_raises_invalid_password_for_weak_new_password(
        self,
        mocker: MockerFixture,
        faker: Faker,
        old_password: str,
        user: User,
    ) -> None:
        mocker.patch(
            "app.core.services.user.validate_password",
            side_effect=ValidationError(["Password too weak."]),
        )

        with pytest.raises(InvalidPassword) as exc_info:
            await UserService.change_password(
                user=user,
                old_password=old_password,
                new_password=faker.password(),
            )

        assert exc_info.value.messages == ["Password too weak."]
        await user.arefresh_from_db()
        assert await user.acheck_password(old_password)


@pytest.mark.django_db
class TestUserServiceSetRoles:
    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    def test_happy_path(self, user: User) -> None:
        roles = [GlobalRole.ADMIN, GlobalRole.READ_ALL]

        UserService.set_roles(user=user, roles=roles)

        user_roles = list(user.global_role_assignments.values_list("role", flat=True))
        assert set(user_roles) == set(roles)

    def test_replaces_existing_roles(self, user: User) -> None:
        # Create initial roles.
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)

        # Replace with new roles.
        new_roles = [GlobalRole.ADMIN]
        UserService.set_roles(user=user, roles=new_roles)

        user_roles = list(user.global_role_assignments.values_list("role", flat=True))
        assert user_roles == new_roles
        assert GlobalRole.READ_ALL not in user_roles

    def test_removes_all_roles_when_empty_list(self, user: User) -> None:
        # Create initial roles.
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
        GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)

        # Remove all roles.
        UserService.set_roles(user=user, roles=[])

        assert not user.global_role_assignments.exists()

    def test_idempotent_when_setting_same_roles(self, user: User) -> None:
        roles = [GlobalRole.ADMIN, GlobalRole.READ_ALL]

        # Set roles twice.
        UserService.set_roles(user=user, roles=roles)
        UserService.set_roles(user=user, roles=roles)

        user_roles = list(user.global_role_assignments.values_list("role", flat=True))
        assert set(user_roles) == set(roles)
        assert GlobalRoleAssignment.objects.filter(user=user).count() == len(roles)
