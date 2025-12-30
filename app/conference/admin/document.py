from django.contrib import admin

from app.conference.models import AcceptanceLetter


@admin.register(AcceptanceLetter)
class AcceptanceLetterAdmin(admin.ModelAdmin[AcceptanceLetter]):
    list_display = ("paper", "create_time")
    list_filter = ("paper__conference",)
    list_select_related = ("paper__conference", "paper__track__conference")
    autocomplete_fields = ("paper",)
    readonly_fields = ("create_time", "update_time")
    search_fields = ("paper__code", "paper__title")
