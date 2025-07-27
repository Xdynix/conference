from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group

from app.core.models import User

admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
    pass
