from django.contrib import admin
from django.urls import include, path

import app.url_converters  # noqa: F401
from app.admin.views import media
from app.api import api
from app.misc.views import favicon

urlpatterns = [
    path("favicon.ico", favicon, name="favicon"),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("core/", include("app.core.urls")),
    path("media/<path:path>", media, name="media"),
    path("", include("app.frontend.urls")),
]
