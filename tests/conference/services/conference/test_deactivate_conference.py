import pytest

from app.conference.models import Conference
from app.conference.services import ConferenceService
from tests.helpers import update_object


@pytest.mark.django_db
class TestConferenceServiceDeactivateConference:
    def test_happy_path(self, conference: Conference) -> None:
        deactivated = ConferenceService.deactivate_conference(name=conference.name)

        db_deactivated = Conference.objects.get(pk=deactivated.pk)
        assert deactivated.active == db_deactivated.active is False

    def test_raises_does_not_exist_for_unknown_conference(self) -> None:
        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.deactivate_conference(name="missing-conf")

    def test_raises_does_not_exist_for_inactive_conference(
        self,
        conference: Conference,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Conference.DoesNotExist):
            ConferenceService.deactivate_conference(name=conference.name)
