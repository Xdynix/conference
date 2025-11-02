from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from app.core.models import PasswordResetToken, Permission, Role, RoleAssignment, User

admin.site.unregister(Group)


class RoleAssignmentInline(admin.TabularInline[RoleAssignment, User]):
    model = RoleAssignment
    extra = 0
    autocomplete_fields = ("role",)
    readonly_fields = ("create_time", "update_time")


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
    inlines = (RoleAssignmentInline,)
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


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin[Permission]):
    pass


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin[Role]):
    filter_horizontal = ("permissions",)
    search_fields = ("name", "display_name")


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin[PasswordResetToken]):
    date_hierarchy = "create_time"
    list_display = ("__str__", "create_time", "expire_time")
    list_filter = ("create_time", "expire_time", "consume_time")
    ordering = ("-create_time",)
    readonly_fields = ("token_hash",)
    search_fields = ("user__username",)
