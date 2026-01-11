from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView


class PublicView(TemplateView):
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["params"] = self.kwargs
        return context


class ProtectedView(LoginRequiredMixin, PublicView):
    login_url = reverse_lazy("frontend:login")
