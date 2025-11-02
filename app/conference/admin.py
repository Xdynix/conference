from typing import override

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http.request import HttpRequest

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Invitation,
    InvitationTrackEntry,
    Keyword,
    KeywordSet,
    Track,
    TrackRole,
    TrackRoleAssignment,
    UserProfile,
)


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin[Keyword]):
    list_display = ("text",)
    ordering = ("text",)
    search_fields = ("text",)


@admin.register(KeywordSet)
class KeywordSetAdmin(admin.ModelAdmin[KeywordSet]):
    filter_horizontal = ("keywords",)
    list_display = ("name", "keyword_count")
    ordering = ("name",)
    search_fields = ("name",)

    @override
    def get_queryset(
        self,
        request: HttpRequest,
    ) -> QuerySet[KeywordSet]:  # pragma: no cover
        return super().get_queryset(request).annotate(keywords_count=Count("keywords"))

    @admin.display(description="Keywords", ordering="keywords_count")
    def keyword_count(self, obj: KeywordSet) -> int:  # pragma: no cover
        return int(obj.keywords_count)  # type: ignore[attr-defined]


class ConferenceRoleAssignmentInline(
    admin.TabularInline[ConferenceRoleAssignment, Conference]
):
    model = ConferenceRoleAssignment
    extra = 0
    autocomplete_fields = ("user", "role")
    readonly_fields = ("create_time", "update_time")


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin[Conference]):
    date_hierarchy = "create_time"
    filter_horizontal = ("keywords",)
    inlines = (ConferenceRoleAssignmentInline,)
    list_display = ("__str__", "display_name", "active", "create_time")
    list_filter = ("active",)
    readonly_fields = ("create_time", "update_time")
    search_fields = ("name", "display_name")
    # TODO: Add clone operation.


@admin.register(ConferenceRole)
class ConferenceRoleAdmin(admin.ModelAdmin[ConferenceRole]):
    filter_horizontal = ("permissions",)
    search_fields = ("name", "display_name")


class TrackRoleAssignmentInline(admin.TabularInline[TrackRoleAssignment, Track]):
    model = TrackRoleAssignment
    extra = 0
    autocomplete_fields = ("user", "role")
    readonly_fields = ("create_time", "update_time")


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin[Track]):
    date_hierarchy = "create_time"
    inlines = (TrackRoleAssignmentInline,)
    list_display = ("__str__", "active", "create_time")
    list_filter = ("active", "conference")
    list_select_related = ("conference",)
    autocomplete_fields = ("conference",)
    readonly_fields = ("uid", "create_time", "update_time")
    search_fields = ("uid", "display_name", "conference__name")


@admin.register(TrackRole)
class TrackRoleAdmin(admin.ModelAdmin[TrackRole]):
    filter_horizontal = ("permissions",)
    search_fields = ("name", "display_name")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin[UserProfile]):
    list_display = (
        "__str__",
        "given_name",
        "family_name",
        "affiliation",
        "region_code",
    )
    list_filter = ("region_code",)
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    search_fields = (
        "user__username",
        "user__email",
        "given_name",
        "family_name",
        "affiliation",
    )


class InvitationTrackEntryInline(admin.TabularInline[InvitationTrackEntry, Invitation]):
    model = InvitationTrackEntry
    extra = 0
    autocomplete_fields = ("track",)
    filter_horizontal = ("roles",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin[Invitation]):
    date_hierarchy = "create_time"
    filter_horizontal = ("conference_roles",)
    inlines = (InvitationTrackEntryInline,)
    list_display = (
        "__str__",
        "inviter",
        "invitee_user",
        "status",
        "email_send_count",
        "create_time",
    )
    list_filter = ("accept_time", "reject_time", "conference")
    list_select_related = ("conference", "inviter", "invitee_user")
    autocomplete_fields = ("conference", "inviter", "invitee_user")
    readonly_fields = (
        "status",
        "create_time",
        "update_time",
        "last_email_sent_time",
    )
    search_fields = (
        "conference__name",
        "inviter__username",
        "invitee_email",
        "invitee_user__username",
    )
