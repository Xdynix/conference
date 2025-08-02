import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
from faker import Faker

from app.core.models import Permission, Role, RoleAssignment, User
from app.core.services import PermissionService
from tests.helpers import update_object


@pytest.mark.django_db(transaction=True)
class TestPermissionServiceGetPermissions:
    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def perm_read(self) -> Permission:
        return Permission.objects.create(key="read")

    @pytest.fixture
    def perm_write(self) -> Permission:
        return Permission.objects.create(key="write")

    @pytest.fixture
    def perm_delete(self) -> Permission:
        return Permission.objects.create(key="delete")

    @pytest.fixture
    def role_viewer(self, perm_read: Permission) -> Role:
        role = Role.objects.create(name="viewer", display_name="Viewer")
        role.permissions.add(perm_read)
        return role

    @pytest.fixture
    def role_editor(self, perm_read: Permission, perm_write: Permission) -> Role:
        role = Role.objects.create(name="editor", display_name="Editor")
        role.permissions.add(perm_read, perm_write)
        return role

    @pytest.fixture
    def role_admin(
        self,
        perm_read: Permission,
        perm_write: Permission,
        perm_delete: Permission,
    ) -> Role:
        role = Role.objects.create(name="admin", display_name="Administrator")
        role.permissions.add(perm_read, perm_write, perm_delete)
        return role

    @pytest.fixture
    def role_empty(self) -> Role:
        return Role.objects.create(name="empty", display_name="Empty Role")

    async def test_no_assignments(self, user: User) -> None:
        permissions = await PermissionService.get_permissions(user)

        assert permissions == set()

    async def test_single_role(self, user: User, role_viewer: Role) -> None:
        await RoleAssignment.objects.acreate(user=user, role=role_viewer)

        permissions = await PermissionService.get_permissions(user)

        assert permissions == {"read"}

    async def test_multiple_roles_unique_permissions(
        self,
        user: User,
        role_viewer: Role,
        perm_delete: Permission,
    ) -> None:
        # Create a role with unique permission.
        role_deleter = await Role.objects.acreate(
            name="deleter",
            display_name="Deleter",
            description="Can delete content",
        )
        await sync_to_async(role_deleter.permissions.add)(perm_delete)

        await RoleAssignment.objects.acreate(user=user, role=role_viewer)
        await RoleAssignment.objects.acreate(user=user, role=role_deleter)

        permissions = await PermissionService.get_permissions(user)

        assert permissions == {"read", "delete"}

    async def test_multiple_roles_overlapping_permissions(
        self,
        user: User,
        role_viewer: Role,
        role_editor: Role,
    ) -> None:
        await RoleAssignment.objects.acreate(user=user, role=role_viewer)
        await RoleAssignment.objects.acreate(user=user, role=role_editor)

        permissions = await PermissionService.get_permissions(user)

        assert permissions == {"read", "write"}

    async def test_role_with_no_permissions(self, user: User, role_empty: Role) -> None:
        await RoleAssignment.objects.acreate(user=user, role=role_empty)

        permissions = await PermissionService.get_permissions(user)

        assert permissions == set()

    async def test_mixed_roles_with_and_without_permissions(
        self,
        user: User,
        role_viewer: Role,
        role_empty: Role,
    ) -> None:
        await RoleAssignment.objects.acreate(user=user, role=role_viewer)
        await RoleAssignment.objects.acreate(user=user, role=role_empty)

        permissions = await PermissionService.get_permissions(user)

        assert permissions == {"read"}

    async def test_different_users_isolated(
        self,
        faker: Faker,
        role_viewer: Role,
        role_editor: Role,
    ) -> None:
        user1 = await User.objects.acreate_user(username=faker.user_name())
        user2 = await User.objects.acreate_user(username=faker.user_name())

        await RoleAssignment.objects.acreate(user=user1, role=role_viewer)
        await RoleAssignment.objects.acreate(user=user2, role=role_editor)

        permissions1 = await PermissionService.get_permissions(user1)
        permissions2 = await PermissionService.get_permissions(user2)

        assert permissions1 == {"read"}
        assert permissions2 == {"read", "write"}

    async def test_inactive_user(self, user: User, role_viewer: Role) -> None:
        await sync_to_async(update_object)(user, is_active=False)
        await RoleAssignment.objects.acreate(user=user, role=role_viewer)

        permissions = await PermissionService.get_permissions(user)

        assert permissions == set()

    async def test_anonymous_user(self) -> None:
        user = AnonymousUser()

        permissions = await PermissionService.get_permissions(user)

        assert permissions == set()

    async def test_superuser(
        self,
        user: User,
        perm_read: Permission,
        perm_write: Permission,
        perm_delete: Permission,
    ) -> None:
        await sync_to_async(update_object)(user, is_superuser=True)
        await Permission.objects.exclude(
            key__in=[perm_read.key, perm_write.key, perm_delete.key]
        ).adelete()

        permissions = await PermissionService.get_permissions(user)

        assert permissions == {"read", "write", "delete"}

    async def test_inactive_superuser(
        self,
        user: User,
        perm_read: Permission,  # noqa: ARG002
        perm_write: Permission,  # noqa: ARG002
        perm_delete: Permission,  # noqa: ARG002
    ) -> None:
        await sync_to_async(update_object)(user, is_active=False, is_superuser=True)

        permissions = await PermissionService.get_permissions(user)

        assert permissions == set()

    async def test_superuser_no_permissions_in_db(self, user: User) -> None:
        await sync_to_async(update_object)(user, is_superuser=True)
        await Permission.objects.all().adelete()

        permissions = await PermissionService.get_permissions(user)

        # If no permissions exist in database, superuser gets empty set.
        assert permissions == set()
