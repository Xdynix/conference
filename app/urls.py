from django.contrib import admin
from django.urls import include, path, register_converter
from ulid_django.converters import ULIDConverter

from app.admin.views import media
from app.api import api
from app.misc.views import favicon

register_converter(ULIDConverter, "ulid")

urlpatterns = [
    path("favicon.ico", favicon, name="favicon"),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("core/", include("app.core.urls")),
    path("media/<path:path>", media, name="media"),
]
