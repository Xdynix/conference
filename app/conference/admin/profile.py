from django.contrib import admin

from app.conference.models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin[Profile]):
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
