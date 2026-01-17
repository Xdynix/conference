from datetime import date

import pytest
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceVisibility,
    Keyword,
    KeywordSet,
    TrackVisibility,
)
from app.conference.services import ConferenceService
from app.conference.services.conference import ConferenceNameConflict, TrackData


@pytest.mark.django_db
class TestConferenceServiceCreateConference:
    def test_happy_path(self, faker: Faker) -> None:
        name = faker.slug()
        display_name = faker.sentence()
        visibility = ConferenceVisibility.PUBLIC
        registration_enabled = True
        start_date = date(2026, 9, 24)
        end_date = date(2026, 9, 27)
        location = "Cagliari, Italy"

        conference = ConferenceService.create_conference(
            name=name,
            display_name=display_name,
            visibility=visibility,
            registration_enabled=registration_enabled,
            keywords=[],
            keyword_sets=[],
            tracks=[],
            start_date=start_date,
            end_date=end_date,
            location=location,
        )

        db_conference = Conference.objects.get(pk=conference.pk)
        assert conference.name == db_conference.name == name
        assert conference.display_name == db_conference.display_name == display_name
        assert conference.visibility == db_conference.visibility == visibility
        assert (
            conference.registration_enabled
            == db_conference.registration_enabled
            == registration_enabled
        )
        assert conference.start_date == db_conference.start_date == start_date
        assert conference.end_date == db_conference.end_date == end_date
        assert conference.location == db_conference.location == location
        assert not db_conference.keywords.exists()
        assert db_conference.tracks.count() == 0

    def test_creates_conference_with_keywords(self, faker: Faker) -> None:
        keyword1 = Keyword.objects.create(text="machine-learning")
        keyword2 = Keyword.objects.create(text="ai")

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.ADMIN_ONLY,
            registration_enabled=False,
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
            visibility=ConferenceVisibility.ADMIN_ONLY,
            registration_enabled=False,
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
            visibility=ConferenceVisibility.ADMIN_ONLY,
            registration_enabled=False,
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
            visibility=ConferenceVisibility.ADMIN_ONLY,
            registration_enabled=False,
            keywords=[keyword1],
            keyword_sets=[keyword_set],
            tracks=[],
        )

        assert set(conference.keywords.all()) == {keyword1, keyword2}

    def test_creates_conference_with_tracks(self, faker: Faker) -> None:
        tracks = [
            TrackData(display_name=display_name, visibility=visibility)
            for display_name, visibility in [
                ("Track A", TrackVisibility.PUBLIC),
                ("Track B", TrackVisibility.ADMIN_ONLY),
                ("Track C", TrackVisibility.PUBLIC),
            ]
        ]

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
            registration_enabled=False,
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
        assert db_track_a.visibility == TrackVisibility.PUBLIC
        assert db_track_b.display_name == "Track B"
        assert db_track_b.ordering == 1
        assert db_track_b.visibility == TrackVisibility.ADMIN_ONLY
        assert db_track_c.display_name == "Track C"
        assert db_track_c.ordering == 2
        assert db_track_c.visibility == TrackVisibility.PUBLIC

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
                visibility=ConferenceVisibility.PUBLIC,
                registration_enabled=False,
                keywords=[],
                keyword_sets=[],
                tracks=[],
            )

        assert Conference.objects.filter(name=existing_conference.name).count() == 1

    def test_creates_conference_with_display_fields_null(self, faker: Faker) -> None:
        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
            registration_enabled=False,
            keywords=[],
            keyword_sets=[],
            tracks=[],
        )

        db_conference = Conference.objects.get(pk=conference.pk)
        assert db_conference.start_date is None
        assert db_conference.end_date is None
        assert db_conference.location == ""

    def test_creates_conference_with_partial_display_fields(self, faker: Faker) -> None:
        start_date = date(2026, 9, 24)

        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
            registration_enabled=False,
            keywords=[],
            keyword_sets=[],
            tracks=[],
            start_date=start_date,
            location="Remote",
        )

        db_conference = Conference.objects.get(pk=conference.pk)
        assert db_conference.start_date == start_date
        assert db_conference.end_date is None
        assert db_conference.location == "Remote"

    def test_creates_conference_with_paper_instructions(self, faker: Faker) -> None:
        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
            registration_enabled=False,
            keywords=[],
            keyword_sets=[],
            tracks=[],
            paper_submission_instructions="**Submit as PDF**",
            paper_final_instructions="Use the template",
        )

        db_conference = Conference.objects.get(pk=conference.pk)
        assert db_conference.paper_submission_instructions == "**Submit as PDF**"
        assert db_conference.paper_final_instructions == "Use the template"

    def test_creates_conference_with_empty_paper_instructions_by_default(
        self, faker: Faker
    ) -> None:
        conference = ConferenceService.create_conference(
            name=faker.slug(),
            display_name=faker.sentence(),
            visibility=ConferenceVisibility.PUBLIC,
            registration_enabled=False,
            keywords=[],
            keyword_sets=[],
            tracks=[],
        )

        db_conference = Conference.objects.get(pk=conference.pk)
        assert db_conference.paper_submission_instructions == ""
        assert db_conference.paper_final_instructions == ""
