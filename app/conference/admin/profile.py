from django.contrib import admin

from app.conference.models import Profile, UserConferenceProfile


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


@admin.register(UserConferenceProfile)
class UserConferenceProfileAdmin(admin.ModelAdmin[UserConferenceProfile]):
    filter_horizontal = ("interested_keywords",)
    list_display = (
        "__str__",
        "create_time",
    )
    list_filter = ("conference",)
    list_select_related = ("user", "conference")
    autocomplete_fields = ("user", "conference")
    readonly_fields = ("create_time", "update_time")
    search_fields = (
        "user__username",
        "user__email",
        "conference__name",
        "conference__display_name",
    )
