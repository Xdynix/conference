import pytest

from app.conference.models import Registration, RegistrationState
from app.conference.services import RegistrationService
from app.conference.services.registration import InvalidRegistrationStateError
from tests.helpers import update_object


@pytest.mark.django_db
class TestCancelRegistrationAuthorMode:
    def test_happy_path(self, registration: Registration) -> None:
        result = RegistrationService.cancel_registration(registration, mode="author")

        db_result = Registration.objects.get(pk=result.pk)
        assert result.state == db_result.state == RegistrationState.CANCELLED

    def test_rejects_confirmed_state(self, registration: Registration) -> None:
        update_object(registration, state=RegistrationState.CONFIRMED)

        with pytest.raises(
            InvalidRegistrationStateError,
            match="Only pending registrations can be cancelled",
        ):
            RegistrationService.cancel_registration(registration, mode="author")

        registration.refresh_from_db()
        assert registration.state == RegistrationState.CONFIRMED

    def test_rejects_already_cancelled(self, registration: Registration) -> None:
        update_object(registration, state=RegistrationState.CANCELLED)

        with pytest.raises(
            InvalidRegistrationStateError,
            match="Only pending registrations can be cancelled",
        ):
            RegistrationService.cancel_registration(registration, mode="author")

    def test_deleted_registration_raises_error(
        self,
        registration: Registration,
    ) -> None:
        registration.delete()

        with pytest.raises(Registration.DoesNotExist):
            RegistrationService.cancel_registration(registration, mode="author")


@pytest.mark.django_db
class TestCancelRegistrationAdminMode:
    def test_happy_path_pending_state(self, registration: Registration) -> None:
        result = RegistrationService.cancel_registration(registration, mode="admin")

        db_result = Registration.objects.get(pk=result.pk)
        assert result.state == db_result.state == RegistrationState.CANCELLED

    def test_happy_path_confirmed_state(self, registration: Registration) -> None:
        update_object(registration, state=RegistrationState.CONFIRMED)

        result = RegistrationService.cancel_registration(registration, mode="admin")

        db_result = Registration.objects.get(pk=result.pk)
        assert result.state == db_result.state == RegistrationState.CANCELLED

    def test_rejects_already_cancelled(self, registration: Registration) -> None:
        update_object(registration, state=RegistrationState.CANCELLED)

        with pytest.raises(
            InvalidRegistrationStateError,
            match="Registration is already cancelled",
        ):
            RegistrationService.cancel_registration(registration, mode="admin")

    def test_deleted_registration_raises_error(
        self,
        registration: Registration,
    ) -> None:
        registration.delete()

        with pytest.raises(Registration.DoesNotExist):
            RegistrationService.cancel_registration(registration, mode="admin")
