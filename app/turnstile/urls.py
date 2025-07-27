from django.urls import path

from app.turnstile import views

app_name = "turnstile"
urlpatterns = [
    path("demo/", views.demo, name="demo"),
    path("demo-api/", views.demo_api, name="demo-api"),
]
