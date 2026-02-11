from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import conditional_page
from django.views.generic import TemplateView
from ulid import ULID

# Caching strategy
#
# These views are pure TemplateViews with no database queries. All user-specific data is
# fetched client-side via Alpine.js and API calls. The only server-side context is URL
# params and settings-derived template tags (enums, branding, URLs), making the rendered
# HTML deterministic for a given URL and deployment.
#
# This lets us use ETag-based caching:
#   - ensure_csrf_cookie: sets the CSRF token via cookie instead of embedding it in the
#     HTML, keeping the response deterministic.
#   - conditional_page: computes an ETag from the response body and returns 304 when the
#     browser's cached copy matches, saving bandwidth.
#   - cache_control(no_cache=True): forces browsers to always revalidate against the
#     ETag rather than relying on heuristic caching. This guarantees fresh content after
#     deployments (when template output changes and the ETag shifts).
#
# To preserve this, do not add per-request or per-user data to the template context.
# The CSRF token must stay in the cookie (not in the HTML body).


@method_decorator(
    [
        ensure_csrf_cookie,
        conditional_page,
        cache_control(no_cache=True),
    ],
    name="dispatch",
)
class PublicView(TemplateView):
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["params"] = {
            k: str(v) if isinstance(v, ULID) else v for k, v in self.kwargs.items()
        }
        return context


class ProtectedView(LoginRequiredMixin, PublicView):
    login_url = reverse_lazy("frontend:login")
