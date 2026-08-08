from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from app.core.models import ApiKey, GlobalRoleAssignment, PasswordResetToken, User

admin.site.unregister(Group)


class GlobalRoleAssignmentInline(admin.TabularInline[GlobalRoleAssignment, User]):
    model = GlobalRoleAssignment
    extra = 0
    readonly_fields = ("create_time", "update_time")


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
    inlines = (GlobalRoleAssignmentInline,)
    fieldsets = (
        (
            None,
            {"fields": ("username", "password")},
        ),
        (
            _("Personal info"),
            {"fields": ("managed", "email")},
            # Removed first/last name, added `managed`.
        ),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser")},
            # Removed `groups` and `user_permissions`.
        ),
        (
            _("Important dates"),
            {"fields": ("last_login", "date_joined")},
        ),
    )


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin[PasswordResetToken]):
    date_hierarchy = "create_time"
    list_display = ("__str__", "create_time", "expire_time")
    list_filter = ("create_time", "expire_time", "consume_time")
    list_select_related = ("user",)
    ordering = ("-create_time",)
    autocomplete_fields = ("user",)
    readonly_fields = ("token_hash",)
    search_fields = ("user__username",)


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin[ApiKey]):
    date_hierarchy = "create_time"
    list_display = ("user", "create_time", "last_use_time", "revoke_time")
    list_filter = ("create_time", "revoke_time")
    list_select_related = ("user",)
    ordering = ("-create_time",)
    autocomplete_fields = ("user",)
    readonly_fields = ("hashed_key", "auth_hash", "create_time", "last_use_time")
    search_fields = ("user__username",)
