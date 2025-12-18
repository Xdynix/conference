from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpRequest
from django.views.decorators.http import require_GET


@admin.site.admin_view
@require_GET
def media(_: HttpRequest, path: str) -> FileResponse:
    """Serves media files rendered for file fields in Django admin.

    This view supplements the admin site by serving file field URLs with the same
    permission check. It is not intended for business logic related downloads;
    those should use dedicated endpoints with domain-specific access control.
    """
    resolved = (settings.MEDIA_ROOT / path).resolve()
    if not resolved.is_relative_to(settings.MEDIA_ROOT):
        raise PermissionDenied

    if not resolved.is_file():
        raise Http404

    return FileResponse(resolved.open("rb"))
