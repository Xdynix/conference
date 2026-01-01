from django.contrib import admin

from app.conference.models import (
    AttendanceType,
    CodePool,
    Conference,
    ConferenceRoleAssignment,
    Track,
    TrackRoleAssignment,
)


class AttendanceTypeInline(admin.TabularInline[AttendanceType, Conference]):
    model = AttendanceType
    extra = 0
    readonly_fields = ("uid",)


class ConferenceRoleAssignmentInline(
    admin.TabularInline[ConferenceRoleAssignment, Conference]
):
    model = ConferenceRoleAssignment
    extra = 0
    autocomplete_fields = ("user",)
    readonly_fields = ("create_time", "update_time")


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin[Conference]):
    date_hierarchy = "create_time"
    filter_horizontal = ("keywords",)
    inlines = (AttendanceTypeInline, ConferenceRoleAssignmentInline)
    list_display = (
        "__str__",
        "display_name",
        "visibility",
        "registration_enabled",
        "active",
        "create_time",
    )
    list_filter = ("active", "visibility", "registration_enabled")
    readonly_fields = ("create_time", "update_time")
    search_fields = ("name", "display_name")


@admin.register(CodePool)
class CodePoolAdmin(admin.ModelAdmin[CodePool]):
    date_hierarchy = "create_time"
    list_display = ("name", "conference", "prefix", "next_sequence", "create_time")
    list_filter = ("conference",)
    list_select_related = ("conference",)
    ordering = ("-create_time",)
    autocomplete_fields = ("conference",)
    readonly_fields = ("uid", "create_time", "update_time")
    search_fields = ("uid", "name", "prefix", "conference__name")


class TrackRoleAssignmentInline(admin.TabularInline[TrackRoleAssignment, Track]):
    model = TrackRoleAssignment
    extra = 0
    autocomplete_fields = ("track", "user")
    readonly_fields = ("create_time", "update_time")


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin[Track]):
    date_hierarchy = "create_time"
    inlines = (TrackRoleAssignmentInline,)
    list_display = (
        "__str__",
        "visibility",
        "submissions_enabled",
        "active",
        "create_time",
    )
    list_filter = ("active", "visibility", "submissions_enabled", "conference")
    list_select_related = ("conference", "code_pool")
    autocomplete_fields = ("conference", "code_pool")
    readonly_fields = ("uid", "create_time", "update_time")
    search_fields = ("uid", "display_name", "conference__name")
