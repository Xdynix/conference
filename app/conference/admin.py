from typing import override

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http.request import HttpRequest

from app.conference.models import (
    Conference,
    ConferenceRoleAssignment,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Keyword,
    KeywordSet,
    Track,
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
    autocomplete_fields = ("user",)
    readonly_fields = ("create_time", "update_time")


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin[Conference]):
    date_hierarchy = "create_time"
    filter_horizontal = ("keywords",)
    inlines = (ConferenceRoleAssignmentInline,)
    list_display = ("__str__", "display_name", "visibility", "active", "create_time")
    list_filter = ("active", "visibility")
    readonly_fields = ("create_time", "update_time")
    search_fields = ("name", "display_name")
    # TODO: Add clone operation.


class TrackRoleAssignmentInline(admin.TabularInline[TrackRoleAssignment, Track]):
    model = TrackRoleAssignment
    extra = 0
    autocomplete_fields = ("track", "user")
    readonly_fields = ("create_time", "update_time")


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin[Track]):
    date_hierarchy = "create_time"
    inlines = (TrackRoleAssignmentInline,)
    list_display = ("__str__", "visibility", "active", "create_time")
    list_filter = ("active", "visibility", "conference")
    list_select_related = ("conference",)
    autocomplete_fields = ("conference",)
    readonly_fields = ("uid", "create_time", "update_time")
    search_fields = ("uid", "display_name", "conference__name")


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


class InvitationConferenceRoleEntryInline(
    admin.TabularInline[InvitationConferenceRoleEntry, Invitation]
):
    model = InvitationConferenceRoleEntry
    extra = 0


class InvitationTrackRoleEntryInline(
    admin.TabularInline[InvitationTrackRoleEntry, Invitation]
):
    model = InvitationTrackRoleEntry
    extra = 0
    autocomplete_fields = ("track",)

    def get_queryset(
        self,
        request: HttpRequest,
    ) -> QuerySet[InvitationTrackRoleEntry]:  # pragma: no cover
        return super().get_queryset(request).select_related("track")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin[Invitation]):
    date_hierarchy = "create_time"
    inlines = (
        InvitationConferenceRoleEntryInline,
        InvitationTrackRoleEntryInline,
    )
    filter_horizontal = ("interested_keywords",)
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
