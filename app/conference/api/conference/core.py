from django.contrib.auth.models import AnonymousUser
from ninja import Router

from app.conference.models import Conference
from app.conference.services import ConferenceService
from app.core.models import User

router = Router(tags=["Conference"], exclude_none=True)


async def prefetch_conference(
    conference: Conference,
    user: User | AnonymousUser,
) -> Conference:
    """Prefetch related conference data for efficient serialization.

    Args:
        conference: The conference instance to prefetch data for.
        user: The user requesting the data, used for permission-aware track loading.

    Returns:
        The conference instance with keywords and tracks prefetched.
    """
    conference = await Conference.objects.prefetch_related("keywords").aget(
        pk=conference.pk
    )
    await ConferenceService.prefetch_tracks(conference, user=user)
    return conference
