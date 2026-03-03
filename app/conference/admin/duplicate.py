from django.contrib import admin

from app.conference.models import (
    DuplicateAcknowledgment,
    DuplicateMatch,
    DuplicateReport,
)


class DuplicateMatchInline(admin.TabularInline[DuplicateMatch, DuplicateReport]):
    model = DuplicateMatch
    extra = 0


@admin.register(DuplicateReport)
class DuplicateReportAdmin(admin.ModelAdmin[DuplicateReport]):
    date_hierarchy = "create_time"
    inlines = (DuplicateMatchInline,)
    list_display = ("__str__", "create_time")
    list_filter = ("state",)
    readonly_fields = ("create_time", "update_time")


@admin.register(DuplicateAcknowledgment)
class DuplicateAcknowledgmentAdmin(admin.ModelAdmin[DuplicateAcknowledgment]):
    date_hierarchy = "create_time"
    list_display = ("__str__", "user", "create_time")
    list_filter = ("conference",)
    list_select_related = ("conference", "user")
    autocomplete_fields = ("paper_a", "paper_b", "conference", "user")
    readonly_fields = ("create_time", "update_time")
