from typing import Any

from django.views.generic import TemplateView


class PublicView(TemplateView):
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["params"] = self.kwargs
        return context
