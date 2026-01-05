from collections import defaultdict
from collections.abc import Collection
from typing import Any, Protocol

from django.conf import settings
from django.db.models import CharField, Prefetch, QuerySet, Value
from django.http import HttpRequest
from django.utils.translation import gettext as _
from ninja import Router, Schema
from pydantic import HttpUrl
from ulid import ULID

from app.conference.models import Invitation, InvitationTrackRoleEntry, Track, TrackRole
from app.conference.services import InvitationService
from app.conference.types import Invitation as InvitationSchema

router = Router(tags=["Invitation"], exclude_none=True)


class InvitationUrlsMixin(Schema):
    token: str
    accept_url: HttpUrl
    reject_url: HttpUrl

    @staticmethod
    def resolve_token(invitation: Invitation) -> str:
        return InvitationService.get_invitation_token(invitation)

    @staticmethod
    def resolve_accept_url(invitation: Invitation) -> HttpUrl:
        return HttpUrl(
            InvitationService.get_accept_url(
                invitation,
                invitation.invitation_accept_page_url,  # type: ignore[attr-defined]
            )
        )

    @staticmethod
    def resolve_reject_url(invitation: Invitation) -> HttpUrl:
        return HttpUrl(
            InvitationService.get_reject_url(
                invitation,
                invitation.invitation_reject_page_url,  # type: ignore[attr-defined]
            )
        )


class InvitationResponse(InvitationUrlsMixin, InvitationSchema):
    invitee_user: ULID | None

    @staticmethod
    def resolve_invitee_user(invitation: Invitation) -> ULID | None:
        return invitation.invitee_user.uid if invitation.invitee_user else None

    @staticmethod
    def resolve_interested_keywords(invitation: Invitation) -> list[str]:
        return [keyword.text for keyword in invitation.interested_keywords.all()]

    @staticmethod
    def resolve_conference_roles(invitation: Invitation) -> list[str]:
        return [entry.role for entry in invitation.conference_role_entries.all()]

    @staticmethod
    def resolve_track_roles(invitation: Invitation) -> list[dict[str, Any]]:
        return [
            {"track": entry.track.uid, "role": entry.role}
            for entry in invitation.active_track_role_entries  # type: ignore[attr-defined]
        ]


class TrackRoleItem(Protocol):
    track: ULID
    role: TrackRole


async def validate_and_group_track_roles(
    track_roles: Collection[TrackRoleItem],
) -> dict[Track, list[TrackRole]]:
    """Validate tracks exist and group roles by track.

    Args:
        track_roles: Collection of objects with track UIDs and role attributes.

    Returns:
        Dict mapping Track objects to lists of TrackRole values.

    Raises:
        ValueError: If any track UIDs are invalid (not found in database).
    """
    track_uids = {track_role.track for track_role in track_roles}

    if not track_uids:
        return {}

    tracks = [
        track async for track in Track.objects.active().filter(uid__in=track_uids)
    ]
    track_objs = {track.uid: track for track in tracks}

    missing_uids = track_uids - set(track_objs)
    if missing_uids:
        message = _("Invalid tracks: {uids}").format(
            uids=", ".join(sorted(str(uid) for uid in missing_uids))
        )
        raise ValueError(message)

    track_roles_mapping: dict[Track, list[TrackRole]] = defaultdict(list)
    for track_role in track_roles:
        track = track_objs[track_role.track]
        track_roles_mapping[track].append(track_role.role)

    return dict(track_roles_mapping)


def with_invitation_prefetch(
    queryset: QuerySet[Invitation],
    request: HttpRequest,  # noqa: ARG001
) -> QuerySet[Invitation]:
    """Apply prefetch_related for invitation serialization to a queryset."""

    # TODO: Replace with `reverse()` after implementing frontend page.
    invitation_accept_page_url = settings.INVITATION_ACCEPT_PAGE_URL
    invitation_reject_page_url = settings.INVITATION_REJECT_PAGE_URL

    return (
        queryset.select_related("conference", "invitee_user")
        .annotate(
            invitation_accept_page_url=Value(
                invitation_accept_page_url,
                output_field=CharField(),
            ),
            invitation_reject_page_url=Value(
                invitation_reject_page_url,
                output_field=CharField(),
            ),
        )
        .prefetch_related(
            "interested_keywords",
            "conference_role_entries",
            Prefetch(
                "track_role_entries",
                queryset=InvitationTrackRoleEntry.objects.filter(
                    track__active=True
                ).select_related("track"),
                to_attr="active_track_role_entries",
            ),
        )
    )


async def prefetch_invitation(
    invitation: Invitation,
    request: HttpRequest,
) -> Invitation:
    """Refetch an invitation with all related data prefetched for serialization."""
    qs = with_invitation_prefetch(Invitation.objects.all(), request)
    return await qs.aget(pk=invitation.pk)
