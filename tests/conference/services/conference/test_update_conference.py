import pytest

from app.conference.models import Conference, ConferenceVisibility, Keyword, KeywordSet
from app.conference.services import ConferenceService
from tests.helpers import update_object


@pytest.mark.django_db
class TestConferenceServiceUpdateConference:
    def test_update_display_name(self, conference: Conference) -> None:
        updated = ConferenceService.update_conference(
            name=conference.name,
            display_name="New Display Name",
        )

        db_updated = Conference.objects.get(pk=conference.pk)
        assert updated.display_name == db_updated.display_name == "New Display Name"

    def test_update_visibility(self, conference: Conference) -> None:
        update_object(conference, visibility=ConferenceVisibility.ADMIN_ONLY)

        updated = ConferenceService.update_conference(
            name=conference.name,
            visibility=ConferenceVisibility.PUBLIC,
        )

        db_updated = Conference.objects.get(pk=conference.pk)
        assert (
            updated.visibility == db_updated.visibility == ConferenceVisibility.PUBLIC
        )

    def test_update_keywords(self, conference: Conference) -> None:
        keyword1 = Keyword.objects.create(text="python")
        keyword2 = Keyword.objects.create(text="django")
        keyword3 = Keyword.objects.create(text="rust")
        conference.keywords.set([keyword1, keyword2])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keywords=[keyword3],
        )

        assert set(updated.keywords.all()) == {keyword3}

    def test_update_keyword_sets(self, conference: Conference) -> None:
        keyword1 = Keyword.objects.create(text="backend")
        keyword2 = Keyword.objects.create(text="frontend")
        keyword_set = KeywordSet.objects.create(name="web-dev")
        keyword_set.keywords.set([keyword1, keyword2])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keyword_sets=[keyword_set],
        )

        assert set(updated.keywords.all()) == {keyword1, keyword2}

    def test_update_combines_keywords_and_keyword_sets(
        self,
        conference: Conference,
    ) -> None:
        keyword1 = Keyword.objects.create(text="api")
        keyword2 = Keyword.objects.create(text="microservices")
        keyword3 = Keyword.objects.create(text="cloud")
        keyword_set = KeywordSet.objects.create(name="architecture")
        keyword_set.keywords.set([keyword2, keyword3])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keywords=[keyword1],
            keyword_sets=[keyword_set],
        )

        assert set(updated.keywords.all()) == {keyword1, keyword2, keyword3}

    def test_update_clears_keywords_with_empty_list(
        self,
        conference: Conference,
    ) -> None:
        keyword = Keyword.objects.create(text="docker")
        conference.keywords.set([keyword])

        updated = ConferenceService.update_conference(
            name=conference.name,
            keywords=[],
        )

        assert not updated.keywords.exists()

    def test_update_none_keywords_preserves_existing(
        self,
        conference: Conference,
    ) -> None:
        keyword = Keyword.objects.create(text="kubernetes")
        conference.keywords.set([keyword])

        updated = ConferenceService.update_conference(
            name=conference.name,
            display_name="Updated Name",
        )

        assert updated.display_name == "Updated Name"
        assert set(updated.keywords.all()) == {keyword}

    def test_no_op_when_no_fields_provided(self, conference: Conference) -> None:
        update_object(conference, display_name="Original")
        original_update_time = conference.update_time

        ConferenceService.update_conference(name=conference.name)

        conference.refresh_from_db()
        assert conference.display_name == "Original"
        assert conference.update_time == original_update_time

    def test_raises_does_not_exist_for_unknown_conference(self) -> None:
        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.update_conference(
                name="nonexistent-conf",
                display_name="Test",
            )

    def test_raises_does_not_exist_for_inactive_conference(
        self,
        conference: Conference,
    ) -> None:
        update_object(
            conference,
            display_name="Original",
            active=False,
        )
        original_update_time = conference.update_time

        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.update_conference(
                name=conference.name,
                display_name="Updated",
            )

        conference.refresh_from_db()
        assert conference.display_name == "Original"
        assert conference.update_time == original_update_time
