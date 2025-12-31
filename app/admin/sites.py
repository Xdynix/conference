from typing import override

from django.contrib.admin import AdminSite as DefaultAdminSite
from django.http.request import HttpRequest
from django.utils.translation import gettext_lazy as _


class AdminSite(DefaultAdminSite):
    """Custom admin site."""

    index_title = _("Index")

    @property
    def site_header(self) -> str:  # type: ignore[override]
        from django.conf import settings

        return _("{site_name} Administration").format(site_name=settings.SITE_NAME)

    @property
    def site_title(self) -> str:  # type: ignore[override]
        from django.conf import settings

        return _("{site_name} Admin").format(site_name=settings.SITE_NAME)

    @override
    def has_permission(self, request: HttpRequest) -> bool:
        # Restrict admin site to superusers only. Django admin is difficult to secure
        # with fine-grained permissions, and features like autocomplete search can leak
        # data through unprotected queries.
        user = request.user
        return bool(user.is_active and user.is_superuser)


# TODO: Integrate Cloudflare Turnstile with admin login view.
