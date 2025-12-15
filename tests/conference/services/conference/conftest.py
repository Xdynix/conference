import pytest
from faker import Faker

from app.conference.models import Conference
from app.core.models import User


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )
