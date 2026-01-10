from django.template.response import TemplateResponse
from django.test import RequestFactory

from app.frontend.views import PublicView


def test_public_view_context_includes_params(rf: RequestFactory) -> None:
    request = rf.get("/")

    response = PublicView.as_view(template_name="frontend/index.html")(
        request,
        section="landing",
    )

    assert isinstance(response, TemplateResponse)
    assert response.context_data is not None
    assert response.context_data["params"] == {"section": "landing"}
