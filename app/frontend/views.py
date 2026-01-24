from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView
from ulid import ULID


class PublicView(TemplateView):
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["params"] = {
            k: str(v) if isinstance(v, ULID) else v for k, v in self.kwargs.items()
        }
        return context


class ProtectedView(LoginRequiredMixin, PublicView):
    login_url = reverse_lazy("frontend:login")
