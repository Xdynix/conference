from django.urls import path

from app.core import views

app_name = "core"
urlpatterns = [
    path("password-reset/", views.password_reset_page, name="password-reset"),
]
