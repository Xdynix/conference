from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from app.conference.models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin[Registration]):
    date_hierarchy = "create_time"
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "uid",
                    "conference",
                    "reference_code",
                    "state",
                    "user",
                )
            },
        ),
        (
            _("Attendance"),
            {
                "fields": (
                    "paper",
                    "attendance_type",
                    "receipt_title",
                )
            },
        ),
        (
            _("Profile"),
            {
                "fields": (
                    "title",
                    "given_name",
                    "family_name",
                    "affiliation",
                    "region_code",
                    "email",
                    "phone",
                    "self_introduction",
                )
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": (
                    "create_time",
                    "update_time",
                )
            },
        ),
    )
    list_display = (
        "__str__",
        "conference",
        "attendance_type",
        "state",
        "user",
    )
    list_filter = ("state", "conference")
    list_select_related = ("user", "conference", "paper", "attendance_type")
    autocomplete_fields = ("user", "conference", "paper")
    readonly_fields = (
        "uid",
        "reference_code",
        "create_time",
        "update_time",
    )
    search_fields = (
        "reference_code",
        "user__username",
        "user__email",
        "given_name",
        "family_name",
        "affiliation",
        "email",
    )
