from typing import override

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http.request import HttpRequest

from app.conference.models import (
    Keyword,
    KeywordSet,
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
