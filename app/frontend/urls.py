from django.urls import path

from app.frontend import views

public_view = views.PublicView.as_view

app_name = "frontend"
urlpatterns = [
    path("", public_view(template_name="frontend/index.html"), name="index"),
    path("login/", public_view(template_name="frontend/login.html"), name="login"),
]
