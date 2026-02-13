from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from app.conference.models import AdminComment, Review, ReviewerNotificationLog


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin[Review]):
    date_hierarchy = "create_time"
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "uid",
                    "paper",
                    "reviewer",
                    "offline_reviewer_name",
                    "state",
                )
            },
        ),
        (
            _("Scores"),
            {
                "fields": (
                    ("originality", "significance"),
                    ("technical", "reference"),
                    ("presentation", "match_topic"),
                    "recommendation",
                )
            },
        ),
        (
            _("Feedback"),
            {
                "fields": (
                    "contribution",
                    "decision_reason",
                    "comments",
                    "confidential_remarks",
                )
            },
        ),
        (
            _("Assignment"),
            {
                "fields": (
                    "assigner",
                    "assignment_level",
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
                )
            },
        ),
    )
    list_display = (
        "__str__",
        "state",
        "recommendation",
        "submit_time",
        "create_time",
    )
    list_filter = ("state", "assignment_level", "paper__conference")
    list_select_related = ("paper__conference", "paper__track__conference", "reviewer")
    autocomplete_fields = ("paper", "reviewer", "assigner")
    readonly_fields = (
        "uid",
        "create_time",
        "update_time",
        "submit_time",
    )
    search_fields = (
        "uid",
        "paper__code",
        "paper__title",
        "reviewer__email",
        "offline_reviewer_name",
    )


@admin.register(AdminComment)
class AdminCommentAdmin(admin.ModelAdmin[AdminComment]):
    date_hierarchy = "create_time"
    list_display = (
        "__str__",
        "author",
        "create_time",
    )
    list_filter = ("paper__conference",)
    list_select_related = ("paper__conference", "paper__track__conference", "author")
    autocomplete_fields = ("paper", "author")
    readonly_fields = (
        "uid",
        "create_time",
        "update_time",
    )
    search_fields = (
        "uid",
        "paper__code",
        "paper__title",
        "author__email",
    )


@admin.register(ReviewerNotificationLog)
class ReviewerNotificationLogAdmin(admin.ModelAdmin[ReviewerNotificationLog]):
    autocomplete_fields = ("conference", "reviewer")
    list_display = ("reviewer", "conference", "last_notification_time")
    list_filter = ("conference",)
    list_select_related = ("conference", "reviewer")
    search_fields = ("reviewer__email",)
