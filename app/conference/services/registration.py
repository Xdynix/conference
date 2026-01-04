from typing import Literal

from django.utils.translation import gettext as _
from ulid import ULID

from app.conference.models import (
    AttendanceType,
    Registration,
    RegistrationState,
    RegistrationTitle,
)
from app.infra.models import Mutex


class InvalidRegistrationStateError(Exception):
    pass


class AttendanceTypeIncompatibleError(Exception):
    pass


class RegistrationService:
    @classmethod
    def update_registration(
        cls,
        registration: Registration,
        *,
        mode: Literal["admin", "author"],
        state: RegistrationState | None = None,
        attendance_type: ULID | None = None,
        receipt_title: str | None = None,
        title: RegistrationTitle | Literal[""] | None = None,
        given_name: str | None = None,
        family_name: str | None = None,
        affiliation: str | None = None,
        region_code: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        self_introduction: str | None = None,
    ) -> Registration:
        """Update a registration with the provided field values.

        Only fields that are explicitly passed (not ``None``) are modified. Paper is
        immutable for all modes. State and attendance type are immutable for author
        mode but can be changed by admin.

        Args:
            registration: The registration to update.
            mode: Controls state restrictions and field permissions. ``"admin"`` allows
                updates to any registration and can change state and attendance type.
                ``"author"`` allows updates only to registrations in Pending state and
                cannot change state or attendance type.
            state: New registration state. Admin mode only.
            attendance_type: New attendance type UID. Admin mode only; must be
                compatible with the registration's paper presence.
            receipt_title: Name to appear on the receipt.
            title: Honorific title (Prof., Dr., Mr., Ms.) or empty string to clear.
            given_name: Registrant's given name.
            family_name: Registrant's family name.
            affiliation: Institution or organization.
            region_code: ISO region code.
            email: Contact email address.
            phone: Contact phone number.
            self_introduction: Registrant's self introduction.

        Raises:
            Registration.DoesNotExist: If the registration has been deleted.
            InvalidRegistrationStateError: If the registration is not in Pending state
                for author mode.
            ValueError: If ``state`` or ``attendance_type`` is provided in author mode.
            AttendanceType.DoesNotExist: If the specified attendance type does not
                exist for this conference.
            AttendanceTypeIncompatibleError: If the new attendance type requires a
                paper but the registration has none.
        """
        with Mutex.lock_in_transaction(str(registration.pk), namespace="registration"):
            registration = Registration.objects.get(pk=registration.pk)

            if mode != "admin" and registration.state != RegistrationState.PENDING:
                raise InvalidRegistrationStateError(
                    _("Only pending registrations can be updated.")
                )

            update_fields: list[str] = []

            if state is not None:
                if mode != "admin":
                    raise ValueError("`state` can only be changed in admin mode.")
                registration.state = state
                update_fields.append("state")

            if attendance_type is not None:
                if mode != "admin":
                    raise ValueError(
                        "`attendance_type` can only be changed in admin mode."
                    )

                new_attendance_type = AttendanceType.objects.get(
                    conference_id=registration.conference_id,
                    uid=attendance_type,
                )

                if new_attendance_type.paper_required and registration.paper_id is None:
                    raise AttendanceTypeIncompatibleError(
                        _("This attendance type requires a paper.")
                    )
                if (
                    not new_attendance_type.paper_required
                    and registration.paper_id is not None
                ):
                    raise AttendanceTypeIncompatibleError(
                        _("This attendance type does not allow paper selection.")
                    )

                registration.attendance_type = new_attendance_type
                update_fields.append("attendance_type")

            field_updates = {
                "receipt_title": receipt_title,
                "title": title,
                "given_name": given_name,
                "family_name": family_name,
                "affiliation": affiliation,
                "region_code": region_code,
                "email": email,
                "phone": phone,
                "self_introduction": self_introduction,
            }
            for field, value in field_updates.items():
                if value is not None:
                    setattr(registration, field, value)
                    update_fields.append(field)

            if update_fields:
                registration.save(update_fields=[*update_fields, "update_time"])

            return registration

    @classmethod
    def cancel_registration(cls, registration: Registration) -> Registration:
        """Cancel a registration.

        Only registrations in Pending state can be cancelled by authors. Admins should
        use the update endpoint to change registration state directly.

        Raises:
            Registration.DoesNotExist: If the registration has been deleted.
            InvalidRegistrationStateError: If the registration is not in Pending state.
        """
        with Mutex.lock_in_transaction(str(registration.pk), namespace="registration"):
            registration = Registration.objects.get(pk=registration.pk)

            if registration.state != RegistrationState.PENDING:
                raise InvalidRegistrationStateError(
                    _("Only pending registrations can be cancelled.")
                )

            registration.state = RegistrationState.CANCELLED
            registration.save(update_fields=["state", "update_time"])

            return registration
