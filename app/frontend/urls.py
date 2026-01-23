from django.urls import path

from app.frontend import views

public_view = views.PublicView.as_view
protected_view = views.ProtectedView.as_view

app_name = "frontend"
urlpatterns = [
    path("", public_view(template_name="frontend/index.html"), name="index"),
    path("login/", public_view(template_name="frontend/login.html"), name="login"),
    path("signup/", public_view(template_name="frontend/signup.html"), name="signup"),
    path(
        "account/",
        protected_view(template_name="frontend/account.html"),
        name="account",
    ),
    path(
        "password-reset/",
        public_view(template_name="frontend/password-reset.html"),
        name="password-reset",
    ),
    path(
        "password-reset/confirm/",
        public_view(template_name="frontend/password-reset-confirm.html"),
        name="password-reset-confirm",
    ),
    path(
        "invitations/accept/",
        public_view(template_name="frontend/invitation-accept.html"),
        name="invitation-accept",
    ),
    path(
        "invitations/reject/",
        public_view(template_name="frontend/invitation-reject.html"),
        name="invitation-reject",
    ),
    path(
        "<slug:conference_name>/",
        public_view(template_name="frontend/conference/home.html"),
        name="conference-home",
    ),
    path(
        "<slug:conference_name>/papers/",
        protected_view(template_name="frontend/conference/papers/list.html"),
        name="paper-list",
    ),
    path(
        "<slug:conference_name>/papers/new/",
        protected_view(template_name="frontend/conference/papers/new.html"),
        name="paper-new",
    ),
    path(
        "<slug:conference_name>/papers/<slug:paper_code>/",
        protected_view(template_name="frontend/conference/papers/detail.html"),
        name="paper-detail",
    ),
    path(
        "<slug:conference_name>/papers/<slug:paper_code>/feedback/",
        protected_view(template_name="frontend/conference/papers/feedback.html"),
        name="paper-feedback",
    ),
]
