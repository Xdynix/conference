import pytest
from faker import Faker

from app.core.models import GlobalRole, GlobalRoleAssignment, User


@pytest.fixture
def admin_user(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
    return user


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        password=faker.password(),
        email=faker.email(),
    )
