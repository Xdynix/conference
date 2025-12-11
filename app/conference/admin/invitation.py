from django.contrib import admin
from django.db.models import QuerySet
from django.http.request import HttpRequest

from app.conference.models import (
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
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
