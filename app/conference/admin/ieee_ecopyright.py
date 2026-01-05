from django.contrib import admin

from app.conference.models import IEEEeCopyrightConfig


@admin.register(IEEEeCopyrightConfig)
class IEEEeCopyrightConfigAdmin(admin.ModelAdmin[IEEEeCopyrightConfig]):
    autocomplete_fields = ("conference",)
    filter_horizontal = ("exempt_tracks",)
    list_display = ("conference", "publication_title", "article_source")
    list_filter = ("conference",)
    list_select_related = ("conference",)
    search_fields = (
        "conference__name",
        "conference__display_name",
        "publication_title",
        "article_source",
    )
