from django.contrib.auth.models import AnonymousUser
from django.db.models import Prefetch
from ninja import Field, Router

from app.conference.models import Conference
from app.conference.services import ConferenceService
from app.conference.types import Conference as ConferenceSchema
from app.conference.types import Track as TrackSchema
from app.core.models import User

router = Router(tags=["Conference"], exclude_none=True)


class ConferenceResponse(ConferenceSchema):
    # `visible_tracks` is attached via `Prefetch` in the list/detail views rather than
    # being a model field. The validation_alias keeps serialization aligned with the
    # prefetch to avoid extra queries.
    tracks: list[TrackSchema] = Field(validation_alias="visible_tracks")


class ConferenceDetailResponse(ConferenceResponse):
    keywords: list[str]

    @staticmethod
    def resolve_keywords(conference: Conference) -> list[str]:
        return [keyword.text for keyword in conference.keywords.all()]


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
    return (
        await Conference.objects.prefetch_related("keywords")
        .prefetch_related(
            Prefetch(
                "tracks",
                queryset=await ConferenceService.visible_tracks(user),
                to_attr="visible_tracks",
            ),
        )
        .aget(pk=conference.pk)
    )
