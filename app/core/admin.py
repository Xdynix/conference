from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from app.core.models import Permission, Role, RoleAssignment, User

admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
    # Removed `groups` and `user_permissions`.
    fieldsets = (
        (
            None,
            {"fields": ("username", "password")},
        ),
        (
            _("Personal info"),
            {"fields": ("first_name", "last_name", "email")},
        ),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser")},
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


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin[RoleAssignment]):
    list_display = ("__str__", "create_time", "update_time")
    list_filter = ("role__name",)
    list_select_related = ("user", "role")
    autocomplete_fields = ("user",)
    readonly_fields = ("create_time", "update_time")
    search_fields = ("user__username", "role__name")
