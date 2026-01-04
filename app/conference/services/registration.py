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
        immutable for all modes. Attendance type is immutable for author mode but can
        be changed by admin with validation.

        Args:
            registration: The registration to update.
            mode: Controls state restrictions and field permissions. ``"admin"`` allows
                updates to registrations in Pending or Confirmed state and can change
                attendance type. ``"author"`` allows updates only to registrations in
                Pending state and cannot change attendance type.
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
            InvalidRegistrationStateError: If the registration is not in a valid state
                for the given mode.
            ValueError: If ``attendance_type`` is provided in author mode.
            AttendanceType.DoesNotExist: If the specified attendance type does not
                exist for this conference.
            AttendanceTypeIncompatibleError: If the new attendance type requires a
                paper but the registration has none.
        """
        if mode == "admin":
            allowed_states = {RegistrationState.PENDING, RegistrationState.CONFIRMED}
        else:
            allowed_states = {RegistrationState.PENDING}

        with Mutex.lock_in_transaction(str(registration.pk), namespace="registration"):
            registration = Registration.objects.get(pk=registration.pk)

            if registration.state not in allowed_states:
                if mode == "admin":
                    raise InvalidRegistrationStateError(
                        _("Cannot update a cancelled registration.")
                    )
                raise InvalidRegistrationStateError(
                    _("Only pending registrations can be updated.")
                )

            update_fields: list[str] = []

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
    def cancel_registration(
        cls,
        registration: Registration,
        *,
        mode: Literal["admin", "author"],
    ) -> Registration:
        """Cancel a registration.

        Authors can only cancel registrations in Pending state. Admins can cancel any
        registration that is not already cancelled.

        Args:
            registration: The registration to cancel.
            mode: Controls state restrictions. ``"admin"`` allows cancellation of
                registrations in Pending or Confirmed state. ``"author"`` allows
                cancellation only of registrations in Pending state.

        Raises:
            Registration.DoesNotExist: If the registration has been deleted.
            InvalidRegistrationStateError: If the registration is not in a valid state
                for the given mode.
        """
        if mode == "admin":
            allowed_states = {RegistrationState.PENDING, RegistrationState.CONFIRMED}
        else:
            allowed_states = {RegistrationState.PENDING}

        with Mutex.lock_in_transaction(str(registration.pk), namespace="registration"):
            registration = Registration.objects.get(pk=registration.pk)

            if registration.state not in allowed_states:
                if mode == "admin":
                    raise InvalidRegistrationStateError(
                        _("Registration is already cancelled.")
                    )
                raise InvalidRegistrationStateError(
                    _("Only pending registrations can be cancelled.")
                )

            registration.state = RegistrationState.CANCELLED
            registration.save(update_fields=["state", "update_time"])

            return registration
