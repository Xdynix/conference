import pytest
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Conference,
    Registration,
    RegistrationState,
    RegistrationTitle,
)
from app.conference.services import RegistrationService
from app.conference.services.registration import (
    AttendanceTypeIncompatibleError,
    InvalidRegistrationStateError,
)
from tests.helpers import update_object


@pytest.mark.django_db
class TestUpdateRegistrationAuthorMode:
    def test_happy_path(self, registration: Registration) -> None:
        result = RegistrationService.update_registration(
            registration,
            mode="author",
            receipt_title="Updated University",
            title=RegistrationTitle.PROF,
            given_name="Updated",
            family_name="Name",
            affiliation="Updated University",
            region_code="GB",
            email="updated@example.com",
            phone="+1234567890",
            self_introduction="Updated introduction",
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert result.receipt_title == db_result.receipt_title == "Updated University"
        assert result.title == db_result.title == RegistrationTitle.PROF
        assert result.given_name == db_result.given_name == "Updated"
        assert result.family_name == db_result.family_name == "Name"
        assert result.affiliation == db_result.affiliation == "Updated University"
        assert result.region_code == db_result.region_code == "GB"
        assert result.email == db_result.email == "updated@example.com"
        assert result.phone == db_result.phone == "+1234567890"
        assert (
            result.self_introduction
            == db_result.self_introduction
            == "Updated introduction"
        )

    def test_partial_update(self, registration: Registration) -> None:
        original_email = registration.email
        original_phone = registration.phone

        result = RegistrationService.update_registration(
            registration,
            mode="author",
            receipt_title="Partial Update",
            given_name="Partial",
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert result.receipt_title == db_result.receipt_title == "Partial Update"
        assert result.given_name == db_result.given_name == "Partial"
        assert result.email == db_result.email == original_email
        assert result.phone == db_result.phone == original_phone

    def test_preserves_existing_values(self, registration: Registration) -> None:
        update_object(
            registration,
            receipt_title="Original Title",
            given_name="Original",
        )

        result = RegistrationService.update_registration(
            registration,
            mode="author",
            family_name="NewFamily",
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert result.receipt_title == db_result.receipt_title == "Original Title"
        assert result.given_name == db_result.given_name == "Original"
        assert result.family_name == db_result.family_name == "NewFamily"

    def test_no_changes_when_no_fields_provided(
        self,
        registration: Registration,
    ) -> None:
        update_object(registration, receipt_title="Original", given_name="Name")

        result = RegistrationService.update_registration(registration, mode="author")

        db_result = Registration.objects.get(pk=result.pk)
        assert result.receipt_title == db_result.receipt_title == "Original"
        assert result.given_name == db_result.given_name == "Name"

    def test_clear_title_with_empty_string(self, registration: Registration) -> None:
        update_object(registration, title=RegistrationTitle.DR)

        result = RegistrationService.update_registration(
            registration,
            mode="author",
            title="",
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert result.title == db_result.title == ""

    @pytest.mark.parametrize(
        "state",
        [RegistrationState.CONFIRMED, RegistrationState.CANCELLED],
    )
    def test_rejects_non_pending_state(
        self,
        registration: Registration,
        state: RegistrationState,
    ) -> None:
        update_object(registration, state=state)

        with pytest.raises(
            InvalidRegistrationStateError,
            match="Only pending registrations can be updated",
        ):
            RegistrationService.update_registration(
                registration,
                mode="author",
                receipt_title="Should Fail",
            )

        registration.refresh_from_db()
        assert registration.state == state
        assert registration.receipt_title != "Should Fail"

    def test_rejects_attendance_type_change(
        self,
        registration: Registration,
        attendance_type_no_paper: AttendanceType,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="`attendance_type` can only be changed in admin mode",
        ):
            RegistrationService.update_registration(
                registration,
                mode="author",
                attendance_type=attendance_type_no_paper.uid,
            )

    def test_deleted_registration_raises_error(
        self,
        registration: Registration,
    ) -> None:
        registration.delete()

        with pytest.raises(Registration.DoesNotExist):
            RegistrationService.update_registration(
                registration,
                mode="author",
                receipt_title="Should Fail",
            )


@pytest.mark.django_db
class TestUpdateRegistrationAdminMode:
    def test_happy_path_pending_state(self, registration: Registration) -> None:
        result = RegistrationService.update_registration(
            registration,
            mode="admin",
            receipt_title="Admin Updated",
            given_name="AdminEdit",
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert result.receipt_title == db_result.receipt_title == "Admin Updated"
        assert result.given_name == db_result.given_name == "AdminEdit"

    def test_happy_path_confirmed_state(self, registration: Registration) -> None:
        update_object(registration, state=RegistrationState.CONFIRMED)

        result = RegistrationService.update_registration(
            registration,
            mode="admin",
            receipt_title="Admin Updated Confirmed",
            given_name="ConfirmedEdit",
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert (
            result.receipt_title == db_result.receipt_title == "Admin Updated Confirmed"
        )
        assert result.given_name == db_result.given_name == "ConfirmedEdit"
        assert result.state == db_result.state == RegistrationState.CONFIRMED

    def test_rejects_cancelled_state(self, registration: Registration) -> None:
        update_object(registration, state=RegistrationState.CANCELLED)

        with pytest.raises(
            InvalidRegistrationStateError,
            match="Cannot update a cancelled registration",
        ):
            RegistrationService.update_registration(
                registration,
                mode="admin",
                receipt_title="Should Fail",
            )

        registration.refresh_from_db()
        assert registration.state == RegistrationState.CANCELLED
        assert registration.receipt_title != "Should Fail"

    def test_change_attendance_type(
        self,
        registration: Registration,
        conference: Conference,
    ) -> None:
        new_type = AttendanceType.objects.create(
            conference=conference,
            display_name="Poster Presentation",
            paper_required=True,
            admin_only=True,
        )

        result = RegistrationService.update_registration(
            registration,
            mode="admin",
            attendance_type=new_type.uid,
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert result.attendance_type_id == db_result.attendance_type_id == new_type.pk

    def test_change_to_attendance_type_requires_paper_without_paper(
        self,
        registration_no_paper: Registration,
        attendance_type: AttendanceType,
    ) -> None:
        with pytest.raises(
            AttendanceTypeIncompatibleError,
            match="This attendance type requires a paper",
        ):
            RegistrationService.update_registration(
                registration_no_paper,
                mode="admin",
                attendance_type=attendance_type.uid,
            )

        registration_no_paper.refresh_from_db()
        assert registration_no_paper.attendance_type != attendance_type

    def test_change_to_attendance_type_no_paper_with_paper(
        self,
        registration: Registration,
        attendance_type_no_paper: AttendanceType,
    ) -> None:
        with pytest.raises(
            AttendanceTypeIncompatibleError,
            match="This attendance type does not allow paper selection",
        ):
            RegistrationService.update_registration(
                registration,
                mode="admin",
                attendance_type=attendance_type_no_paper.uid,
            )

        registration.refresh_from_db()
        assert registration.attendance_type != attendance_type_no_paper

    def test_attendance_type_not_found(
        self,
        registration: Registration,
    ) -> None:
        with pytest.raises(AttendanceType.DoesNotExist):
            RegistrationService.update_registration(
                registration,
                mode="admin",
                attendance_type=ULID(),
            )

    def test_attendance_type_from_different_conference(
        self,
        registration: Registration,
    ) -> None:
        other_conference = Conference.objects.create(
            name="other-conf",
            display_name="Other Conference",
        )
        other_type = AttendanceType.objects.create(
            conference=other_conference,
            display_name="Other Type",
            paper_required=True,
        )

        with pytest.raises(AttendanceType.DoesNotExist):
            RegistrationService.update_registration(
                registration,
                mode="admin",
                attendance_type=other_type.uid,
            )

    def test_partial_update_preserves_existing(
        self,
        registration: Registration,
    ) -> None:
        update_object(
            registration,
            state=RegistrationState.CONFIRMED,
            receipt_title="Original Title",
            given_name="Original",
        )

        result = RegistrationService.update_registration(
            registration,
            mode="admin",
            family_name="NewFamily",
        )

        db_result = Registration.objects.get(pk=result.pk)
        assert result.receipt_title == db_result.receipt_title == "Original Title"
        assert result.given_name == db_result.given_name == "Original"
        assert result.family_name == db_result.family_name == "NewFamily"

    def test_deleted_registration_raises_error(
        self,
        registration: Registration,
    ) -> None:
        registration.delete()

        with pytest.raises(Registration.DoesNotExist):
            RegistrationService.update_registration(
                registration,
                mode="admin",
                receipt_title="Should Fail",
            )
