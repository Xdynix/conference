from typing import Any

from django.contrib import admin
from django.db.models import ForeignKey
from django.forms import ModelChoiceField
from django.http.request import HttpRequest

from app.conference.models import (
    DuplicateAcknowledgment,
    DuplicateMatch,
    DuplicateReport,
    Paper,
)


class DuplicateMatchInline(admin.TabularInline[DuplicateMatch, DuplicateReport]):
    model = DuplicateMatch
    extra = 0
    autocomplete_fields = ("paper_a", "paper_b")

    def formfield_for_foreignkey(
        self,
        db_field: ForeignKey[Any, Any],
        request: HttpRequest,
        **kwargs: Any,
    ) -> ModelChoiceField[Any] | None:  # pragma: no cover
        # Each autocomplete widget renders str(paper) for its own row, and
        # Paper.__str__ reaches through track to conference.
        if db_field.remote_field.model is Paper:
            kwargs["queryset"] = Paper.objects.select_related("track__conference")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
