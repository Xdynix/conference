from collections.abc import Collection
from typing import Any, NamedTuple

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.core.registry.create_user import create_user_registry
from app.infra.models import Mutex


class InvalidPassword(Exception):
    def __init__(self, messages: Collection[str]) -> None:
        self.messages = list(messages)


class UserIdentityConflict(Exception):
    pass


class CreateUserResult(NamedTuple):
    user: User
    detail: dict[str, Any]


class UserService:
    @classmethod
    @transaction.atomic
    def create_user(
        cls,
        *,
        username: str,
        email: str,
        password: str,
        managed: bool,
        payload: Any,
    ) -> CreateUserResult:
        """Creates a user with password validation.

        Validates the password against Django's password validators and dispatches to
        the ``create_user_registry`` for additional processing.

        Args:
            username: Unique username for the user.
            email: User's email address.
            password: Plain text password (will be hashed).
            managed: Whether the user is managed by the system.
            payload: Additional data passed to create_user_registry handlers.

        Returns:
            A ``CreateUserResult`` containing the new user and a detail dict with
            handler results from the create-user registry.

        Raises:
            InvalidPassword: Password fails Django's validation rules.
            UserIdentityConflict: Username or email already exists.
        """
        # Create a temporary user to validate password.
        temp_user = User(username=username, email=email)
        try:
            validate_password(password, user=temp_user)
        except ValidationError as exc:
            raise InvalidPassword(exc.messages) from exc

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    managed=managed,
                )
        except IntegrityError as exc:
            conditions = Q(username=username)
            if email:  # pragma: no branch
                conditions |= Q(email__iexact=email)
            is_conflict = User.objects.filter(conditions).exists()
            if not is_conflict:  # pragma: no cover
                raise
            raise UserIdentityConflict from exc

        detail = create_user_registry.dispatch(user, payload)

        return CreateUserResult(user, detail)

    @classmethod
    async def update_user(
        cls,
        *,
        user: User,
        username: str | None = None,
        email: str | None = None,
    ) -> User:
        """Updates a user's username and/or email.

        Modifies only the specified fields. If both username and email are ``None``, the
        user remains unchanged.

        Raises:
            UserIdentityConflict: Username or email already exists.
        """
        # No transaction needed: `save(update_fields=[...])` generates a single atomic
        # UPDATE query that sets specific fields directly without reading current
        # values, so there's no read-modify-write cycle or risk of lost updates.
        update_fields: list[str] = []

        if username is not None:
            user.username = username
            update_fields.append("username")

        if email is not None:
            user.email = email
            update_fields.append("email")

        if update_fields:
            try:
                await user.asave(update_fields=update_fields)
            except IntegrityError as exc:
                conditions = Q()
                if username is not None:
                    conditions |= Q(username=username)
                if email is not None and email:
                    conditions |= Q(email__iexact=email)
                if not conditions:  # pragma: no cover
                    raise
                is_conflict = await (
                    User.objects.filter(conditions).exclude(pk=user.pk).aexists()
                )
                if not is_conflict:  # pragma: no cover
                    raise
                raise UserIdentityConflict from exc

        return user

    @classmethod
    async def update_password(
        cls,
        *,
        user: User,
        new_password: str,
    ) -> None:
        """Updates a user's password with validation.

        Raises:
            InvalidPassword: Password fails validation.
        """
        # No transaction needed: `save(update_fields=[...])` generates a single atomic
        # UPDATE query that sets specific fields directly without reading current
        # values, so there's no read-modify-write cycle or risk of lost updates.
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            raise InvalidPassword(exc.messages) from exc

        user.set_password(new_password)
        await user.asave(update_fields=["password"])

    @classmethod
    async def change_password(
        cls,
        *,
        user: User,
        old_password: str,
        new_password: str,
    ) -> None:
        """Changes a user's password after verifying the old password.

        Raises:
            InvalidPassword: Password fails validation.
            ValueError: Old password is incorrect.
        """
        if not await user.acheck_password(old_password):
            raise ValueError(_("Invalid old password."))

        await cls.update_password(user=user, new_password=new_password)

    @classmethod
    def set_roles(
        cls,
        *,
        user: User,
        roles: Collection[GlobalRole],
    ) -> None:
        """Sets the user's global roles, replacing any existing assignments.

        Removes roles not in the provided collection and adds new roles, ignoring
        conflicts if a role assignment already exists.
        """
        with Mutex.lock_in_transaction(str(user.pk), namespace="user_role_assignments"):
            GlobalRoleAssignment.objects.filter(user=user).exclude(
                role__in=roles
            ).delete()
            GlobalRoleAssignment.objects.bulk_create(
                [GlobalRoleAssignment(user=user, role=role) for role in roles],
                ignore_conflicts=True,
            )
