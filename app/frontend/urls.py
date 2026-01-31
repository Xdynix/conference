from django.urls import path

import app.url_converters  # noqa: F401
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
    path(
        "<slug:conference_name>/review-preferences/",
        protected_view(template_name="frontend/conference/review-preferences.html"),
        name="review-preferences",
    ),
    path(
        "<slug:conference_name>/reviews/",
        protected_view(template_name="frontend/conference/reviews/list.html"),
        name="review-list",
    ),
    path(
        "<slug:conference_name>/reviews/<ulid:review_uid>/",
        protected_view(template_name="frontend/conference/reviews/detail.html"),
        name="review-detail",
    ),
    path(
        "<slug:conference_name>/admin/papers/",
        protected_view(template_name="frontend/conference/admin/papers/list.html"),
        name="admin-paper-list",
    ),
    path(
        "<slug:conference_name>/admin/papers/new/",
        protected_view(template_name="frontend/conference/admin/papers/new.html"),
        name="admin-paper-new",
    ),
    path(
        "<slug:conference_name>/admin/papers/<slug:paper_code>/",
        protected_view(template_name="frontend/conference/admin/papers/detail.html"),
        name="admin-paper-detail",
    ),
    path(
        "<slug:conference_name>/admin/papers/<slug:paper_code>/decide/",
        protected_view(template_name="frontend/conference/admin/papers/decide.html"),
        name="admin-paper-decide",
    ),
    path(
        "<slug:conference_name>/admin/papers/<slug:paper_code>/reviews/",
        protected_view(template_name="frontend/conference/admin/papers/reviews.html"),
        name="admin-paper-reviews",
    ),
    path(
        "<slug:conference_name>/admin/papers/<slug:paper_code>/reviews/<ulid:review_uid>/",
        protected_view(
            template_name="frontend/conference/admin/papers/review-detail.html"
        ),
        name="admin-review-detail",
    ),
]
