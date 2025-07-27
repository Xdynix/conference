from django.contrib import admin
from django.urls import include, path

from app.api import api
from app.misc.views import favicon

urlpatterns = [
    path("favicon.ico", favicon, name="favicon"),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("turnstile/", include("app.turnstile.urls")),
]
