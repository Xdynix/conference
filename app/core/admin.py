from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group

from app.core.models import Permission, Role, User

admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
    pass


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin[Permission]):
    pass


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin[Role]):
    filter_horizontal = ("permissions",)
    search_fields = ("name", "display_name")
