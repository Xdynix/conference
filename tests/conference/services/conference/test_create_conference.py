import pytest
from faker import Faker

from app.conference.models import Conference, Keyword, KeywordSet, Track
from app.conference.services import ConferenceService
from app.conference.services.conference import ConferenceNameConflict, TrackData


@pytest.mark.django_db
class TestConferenceServiceCreateConference:
    def test_happy_path(self, faker: Faker) -> None:
        name = faker.slug()
        display_name = faker.sentence()
        visibility = Conference.Visibility.PUBLIC

        conference = ConferenceService.create_conference(
            name=name,
            display_name=display_name,
            visibility=visibility,
            keywords=[],
            keyword_sets=[],
            tracks=[],
        )

        db_conference = Conference.objects.get(pk=conference.pk)
        assert conference.name == db_conference.name == name
        assert conference.display_name == db_conference.display_name == display_name
        assert conference.visibility == db_conference.visibility == visibility
        assert not db_conference.keywords.exists()
        assert db_conference.tracks.count() == 0

    def test_creates_conference_with_keywords(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="machine-learning")
        keyword2 = Keyword.objects.create(text="ai")

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[keyword1, keyword2],
            keyword_sets=[],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2}

    def test_creates_conference_with_keyword_sets(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="nlp")
        keyword2 = Keyword.objects.create(text="deep-learning")
        keyword3 = Keyword.objects.create(text="computer-vision")

        keyword_set1 = KeywordSet.objects.create(name="ml-topics")
        keyword_set1.keywords.set([keyword1, keyword2])

        keyword_set2 = KeywordSet.objects.create(name="vision")
        keyword_set2.keywords.set([keyword3])

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[],
            keyword_sets=[keyword_set1, keyword_set2],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2, keyword3}

    def test_combines_keywords_and_keyword_sets(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="robotics")
        keyword2 = Keyword.objects.create(text="automation")
        keyword3 = Keyword.objects.create(text="control-systems")

        keyword_set = KeywordSet.objects.create(name="robotics-topics")
        keyword_set.keywords.set([keyword2, keyword3])

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[keyword1],
            keyword_sets=[keyword_set],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2, keyword3}

    def test_deduplicates_keywords_from_multiple_sources(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="security")
        keyword2 = Keyword.objects.create(text="cryptography")

        keyword_set = KeywordSet.objects.create(name="security-topics")
        keyword_set.keywords.set([keyword1, keyword2])

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.ADMIN_ONLY,
            keywords=[keyword1],
            keyword_sets=[keyword_set],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2}

    def test_creates_conference_with_tracks(self, faker: Faker) -> None:
        tracks = [
            TrackData(display_name=display_name, visibility=visibility)
            for display_name, visibility in [
                ("Track A", Track.Visibility.PUBLIC),
                ("Track B", Track.Visibility.ADMIN_ONLY),
                ("Track C", Track.Visibility.PUBLIC),
            ]
        ]

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=Conference.Visibility.PUBLIC,
            keywords=[],
            keyword_sets=[],
            tracks=tracks,
        )

        db_tracks = list(
            Conference.objects.get(pk=conference.pk).tracks.order_by("ordering")
        )
        [db_track_a, db_track_b, db_track_c] = db_tracks
        assert db_track_a.display_name == "Track A"
        assert db_track_a.ordering == 0
        assert db_track_a.visibility == Track.Visibility.PUBLIC
        assert db_track_b.display_name == "Track B"
        assert db_track_b.ordering == 1
        assert db_track_b.visibility == Track.Visibility.ADMIN_ONLY
        assert db_track_c.display_name == "Track C"
        assert db_track_c.ordering == 2
        assert db_track_c.visibility == Track.Visibility.PUBLIC

    def test_raises_conference_name_conflict_for_duplicate_name(
        self, faker: Faker
    ) -> None:
        existing_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

        with pytest.raises(ConferenceNameConflict):
            ConferenceService.create_conference(
                name=existing_conference.name,
                display_name=faker.sentence(),
                visibility=Conference.Visibility.PUBLIC,
                keywords=[],
                keyword_sets=[],
                tracks=[],
            )

        assert Conference.objects.filter(name=existing_conference.name).count() == 1
