from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from app.conference.models import (
    Paper,
    PaperAuthor,
    PaperDocument,
    PaperFinal,
    PaperSubmission,
)


class PaperAuthorInline(admin.StackedInline[PaperAuthor, Paper]):
    model = PaperAuthor
    extra = 0
    fields = (
        "ordering",
        ("given_name", "family_name"),
        "affiliation",
        "region_code",
        ("email", "phone"),
        "corresponding",
    )


class PaperSubmissionInline(admin.TabularInline[PaperSubmission, Paper]):
    model = PaperSubmission
    extra = 0
    readonly_fields = ("create_time", "update_time")


class PaperFinalInline(admin.TabularInline[PaperFinal, Paper]):
    model = PaperFinal
    extra = 0
    readonly_fields = ("create_time", "update_time")


class PaperDocumentInline(admin.TabularInline[PaperDocument, Paper]):
    model = PaperDocument
    extra = 0
    readonly_fields = ("create_time", "update_time")


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin[Paper]):
    date_hierarchy = "create_time"
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "uid",
                    "conference",
                    "track",
                    "code",
                    "owner",
                )
            },
        ),
        (
            _("State"),
            {
                "fields": (
                    "state",
                    "announce_time",
                    "withdraw_time",
                    "delete_time",
                )
            },
        ),
        (
            _("Content"),
            {
                "fields": (
                    "title",
                    "abstract",
                    "contribution",
                    "keywords",
                )
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": (
                    "create_time",
                    "update_time",
                    "submit_time",
                    "decide_time",
                )
            },
        ),
    )
    filter_horizontal = ("keywords",)
    inlines = (
        PaperAuthorInline,
        PaperSubmissionInline,
        PaperFinalInline,
        PaperDocumentInline,
    )
    list_display = (
        "__str__",
        "title",
        "state",
        "owner",
        "create_time",
    )
    list_filter = ("state", "conference")
    list_select_related = ("conference", "track__conference", "owner")
    autocomplete_fields = ("conference", "track", "owner")
    readonly_fields = (
        "uid",
        "code",
        "create_time",
        "update_time",
        "submit_time",
        "decide_time",
    )
    search_fields = ("uid", "code", "title", "owner__email", "author__email")
