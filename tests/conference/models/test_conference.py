import pytest
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from faker import Faker

from app.conference.models import CodePool, Conference, Track


class TestConference:
    def test_str(self) -> None:
        assert str(Conference(name="CBPK-2020")) == "CBPK-2020"


@pytest.mark.django_db
class TestCodePool:
    def test_str(self, conference: Conference) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Main Tracks",
            prefix="CBPK-2",
        )
        assert str(pool) == f"{conference.name} - Main Tracks (CBPK-2)"

    def test_create_with_defaults(self, conference: Conference) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Main Tracks",
            prefix="CBPK-2",
        )
        assert pool.next_sequence == 1

    def test_unique_prefix_within_conference(self, conference: Conference) -> None:
        CodePool.objects.create(
            conference=conference,
            name="Main Tracks",
            prefix="CBPK-2",
        )

        with pytest.raises(IntegrityError):
            CodePool.objects.create(
                conference=conference,
                name="Other Pool",
                prefix="CBPK-2",
            )

    def test_same_prefix_different_conference(self, faker: Faker) -> None:
        conference1 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        conference2 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

        CodePool.objects.create(
            conference=conference1,
            name="Main Tracks",
            prefix="CBPK-2",
        )
        CodePool.objects.create(
            conference=conference2,
            name="Main Tracks",
            prefix="CBPK-2",
        )

    def test_allocate_code(self, conference: Conference) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Main Tracks",
            prefix="CBPK-2",
        )

        code1 = pool.allocate_code()
        assert code1 == "CBPK-2001"

        code2 = pool.allocate_code()
        assert code2 == "CBPK-2002"

        pool.refresh_from_db()
        assert pool.next_sequence == 3

    def test_allocate_code_with_different_prefix(self, conference: Conference) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Workshops",
            prefix="CBPK-WS-",
        )

        code = pool.allocate_code()
        assert code == "CBPK-WS-001"

    def test_allocate_code_grows_naturally(self, conference: Conference) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Main Tracks",
            prefix="CBPK-2",
            next_sequence=1000,
        )

        code = pool.allocate_code()
        assert code == "CBPK-21000"


class TestTrack:
    def test_str(self) -> None:
        conference = Conference(name="CBPK-2020")
        track = Track(conference=conference, display_name="Machine Learning")
        assert str(track) == "CBPK-2020 - Machine Learning"

    @pytest.mark.parametrize(
        ("submissions_enabled", "has_pool", "expected"),
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    def test_accepts_submissions(
        self,
        submissions_enabled: bool,
        has_pool: bool,
        expected: bool,
    ) -> None:
        track = Track(
            submissions_enabled=submissions_enabled,
            code_pool_id=1 if has_pool else None,
        )
        assert track.accepts_submissions is expected

    @pytest.mark.django_db
    def test_protect_pool(self, conference: Conference) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Main Tracks",
            prefix="CBPK-2",
        )
        Track.objects.create(
            conference=conference,
            code_pool=pool,
            display_name="Machine Learning",
        )

        with pytest.raises(ProtectedError):
            pool.delete()
