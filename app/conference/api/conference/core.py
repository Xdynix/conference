from django.contrib.auth.models import AnonymousUser
from django.db.models import (
    BooleanField,
    Exists,
    ExpressionWrapper,
    OuterRef,
    Prefetch,
    QuerySet,
)
from ninja import Field, Router

from app.conference.models import (
    Conference,
    ConferenceRoleAssignment,
    IEEEeCopyrightConfig,
    TrackRoleAssignment,
    UserConferenceProfile,
)
from app.conference.services import ConferenceService
from app.conference.types import Conference as ConferenceSchema
from app.conference.types import IEEEeCopyrightConfig as IEEEeCopyrightConfigSchema
from app.conference.types import Track as BaseTrackSchema
from app.core.models import User

router = Router(tags=["Conference"], exclude_none=True)

# TODO: Add a `/conferences/{name}/my-dashboard` endpoint to return user-specific stats
#  and action items (e.g., pending review count, in-progress review count, upcoming
#  deadlines). This avoids requiring the frontend to call `list-my-reviews` on every
#  page load just to display sidebar badges.


class TrackSchema(BaseTrackSchema):
    ieee_ecopyright_required: bool


class ConferenceResponse(ConferenceSchema):
    # `visible_tracks` is attached via `Prefetch` in the list/detail views rather than
    # being a model field. The validation_alias keeps serialization aligned with the
    # prefetch to avoid extra queries.
    tracks: list[TrackSchema] = Field(validation_alias="visible_tracks")  # type: ignore[assignment]


class ConferenceDetailResponse(ConferenceResponse):
    keywords: list[str]
    ieee_ecopyright_config: IEEEeCopyrightConfigSchema | None = None
    paper_submission_instructions_html: str
    paper_final_instructions_html: str

    @staticmethod
    def resolve_keywords(conference: Conference) -> list[str]:
        return [keyword.text for keyword in conference.keywords.all()]


async def with_conference_prefetch(
    queryset: QuerySet[Conference],
    user: User | AnonymousUser,
) -> QuerySet[Conference]:
    """Prefetch related data for conference queries."""
    visible_tracks = await ConferenceService.visible_tracks(user)
    config_exists = Exists(
        IEEEeCopyrightConfig.objects.filter(
            conference_id=OuterRef("conference_id"),
        ),
    )
    exempt_exists = Exists(
        IEEEeCopyrightConfig.exempt_tracks.through.objects.filter(
            ieeeecopyrightconfig__conference_id=OuterRef("conference_id"),
            track_id=OuterRef("pk"),
        ),
    )
    visible_tracks = visible_tracks.annotate(
        ieee_ecopyright_required=ExpressionWrapper(
            config_exists & ~exempt_exists,
            output_field=BooleanField(),
        )
    )

    return queryset.prefetch_related(
        Prefetch(
            "tracks",
            queryset=visible_tracks,
            to_attr="visible_tracks",
        )
    )


async def prefetch_conference(
    conference: Conference,
    user: User | AnonymousUser,
) -> Conference:
    """Prefetch related conference data for efficient serialization."""
    qs = await with_conference_prefetch(Conference.objects.all(), user)
    qs = qs.select_related("ieee_ecopyright_config").prefetch_related("keywords")
    return await qs.aget(pk=conference.pk)


async def prefetch_user_profile(
    profile: UserConferenceProfile,
    user: User,
) -> UserConferenceProfile:
    """Prefetch related user profile data for efficient serialization.

    Args:
        profile: The user profile instance to prefetch data for.
        user: The user requesting the data, used for permission-aware track loading.

    Returns:
        The user profile instance with keywords and roles prefetched.
    """
    conference_id = profile.conference_id
    visible_tracks = await ConferenceService.visible_tracks(user)
    visible_conference_tracks = visible_tracks.filter(conference_id=conference_id)
    return await (
        UserConferenceProfile.objects.select_related("user")
        .prefetch_related(
            "interested_keywords",
            Prefetch(
                "user__conference_role_assignments",
                queryset=ConferenceRoleAssignment.objects.filter(
                    conference_id=conference_id
                ).order_by("role"),
                to_attr="prefetched_conference_roles",
            ),
            Prefetch(
                "user__track_role_assignments",
                queryset=TrackRoleAssignment.objects.filter(
                    track__in=visible_conference_tracks
                )
                .select_related("track")
                .order_by("track__ordering", "track__display_name", "role"),
                to_attr="prefetched_track_roles",
            ),
        )
        .aget(pk=profile.pk)
    )
