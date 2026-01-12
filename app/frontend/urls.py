from django.urls import path

from app.frontend import views

public_view = views.PublicView.as_view
protected_view = views.ProtectedView.as_view

app_name = "frontend"
urlpatterns = [
    path("", public_view(template_name="frontend/index.html"), name="index"),
    path("login/", public_view(template_name="frontend/login.html"), name="login"),
    path(
        "password-reset/",
        public_view(template_name="frontend/password-reset.html"),
        name="password-reset",
    ),
    path(
        "account/",
        protected_view(template_name="frontend/account.html"),
        name="account",
    ),
]
