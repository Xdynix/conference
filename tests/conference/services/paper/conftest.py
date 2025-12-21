import pytest
from faker import Faker

from app.conference.models import CodePool, Conference, Track


@pytest.fixture
def code_pool(conference: Conference) -> CodePool:
    return CodePool.objects.create(
        conference=conference,
        name="Main Pool",
        prefix="TEST-",
    )


@pytest.fixture
def track_with_pool(faker: Faker, conference: Conference, code_pool: CodePool) -> Track:
    return Track.objects.create(
        conference=conference,
        code_pool=code_pool,
        display_name=faker.word(),
    )
