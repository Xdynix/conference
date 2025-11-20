from http import HTTPStatus

from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import Field, PatchDict, Schema
from ninja.errors import HttpError
from ulid import ULID

from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    Keyword,
    UserConferenceProfile,
)
from app.conference.services import ConferenceService
from app.conference.types import DesiredPaperCount
from app.conference.types import Keyword as KeywordText
from app.core.auth import has_any_roles, is_authenticated
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest

from .core import router


class UserConferenceProfileResponse(Schema):
    desired_paper_count: DesiredPaperCount
    interested_keywords: list[KeywordText]

    @staticmethod
    def resolve_interested_keywords(profile: UserConferenceProfile) -> list[str]:
        return [keyword.text for keyword in profile.interested_keywords.all()]


async def get_visible_conference(user: User, conference_name: str) -> Conference:
    conferences = await ConferenceService.visible_conferences(user)
    return await aget_object_or_404(conferences, name=conference_name)


async def ensure_profile(
    *, user: User, conference: Conference
) -> UserConferenceProfile:
    profile, _ = await UserConferenceProfile.objects.aget_or_create(
        user=user,
        conference=conference,
    )
    return profile


async def load_profile(profile: UserConferenceProfile) -> UserConferenceProfile:
    return await UserConferenceProfile.objects.prefetch_related(
        "interested_keywords"
    ).aget(pk=profile.pk)


@router.get(
    "/conferences/{slug:conference_name}/users/me/profile",
    response=UserConferenceProfileResponse,
    summary="Get My Conference Profile",
    auth=is_authenticated,
)
async def get_current_user_conference_profile(
    request: AuthedHttpRequest,
    conference_name: str,
) -> UserConferenceProfile:
    """Return the current user's profile for the given conference."""
    user = await request.auser()
    conference = await get_visible_conference(user, conference_name)

    profile = await ensure_profile(user=user, conference=conference)
    return await load_profile(profile)


@router.get(
    "/conferences/{slug:conference_name}/users/{ulid:user_id}/profile",
    response=UserConferenceProfileResponse,
    summary="Get User Conference Profile",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def get_user_conference_profile(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    user_id: ULID,
) -> UserConferenceProfile:
    """Return a user's profile for the given conference."""
    conference = await aget_object_or_404(
        Conference.objects.filter(active=True),
        name=conference_name,
    )
    user = await aget_object_or_404(
        User.objects.filter(is_active=True),
        uid=user_id,
    )

    profile = await ensure_profile(user=user, conference=conference)
    return await load_profile(profile)


async def resolve_keywords(keyword_texts: list[str]) -> list[Keyword]:
    provided = set(keyword_texts)
    if not provided:  # pragma: no cover
        return []

    keywords = [keyword async for keyword in Keyword.objects.filter(text__in=provided)]
    missing = provided - {keyword.text for keyword in keywords}
    if missing:
        message = _("Unknown keywords: {keywords}.").format(
            keywords=", ".join(sorted(missing)),
        )
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)
    return keywords


class UserConferenceProfileSchema(Schema):
    desired_paper_count: DesiredPaperCount
    interested_keywords: list[KeywordText] = Field(max_length=100)


async def patch_profile(
    profile: UserConferenceProfile,
    payload: PatchDict[UserConferenceProfileSchema],
) -> None:
    keywords: list[Keyword] | None = None
    if "interested_keywords" in payload:  # pragma: no branch
        keywords = await resolve_keywords(payload["interested_keywords"])

    if "desired_paper_count" in payload:
        profile.desired_paper_count = payload["desired_paper_count"]
        await profile.asave(update_fields=["desired_paper_count", "update_time"])

    if keywords is not None:  # pragma: no branch
        await profile.interested_keywords.aset(keywords)


@router.patch(
    "/conferences/{slug:conference_name}/users/me/profile",
    response=UserConferenceProfileResponse,
    summary="Update My Conference Profile",
    auth=is_authenticated,
)
async def update_current_user_conference_profile(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: PatchDict[UserConferenceProfileSchema],
) -> UserConferenceProfile:
    """Update the current user's profile for the given conference."""
    user = await request.auser()
    conference = await get_visible_conference(user, conference_name)

    profile = await ensure_profile(user=user, conference=conference)
    if payload:  # pragma: no branch
        await patch_profile(profile, payload)

        logger.info(
            "User updated conference profile.",
            user=user,
            conference=conference,
        )
    return await load_profile(profile)


@router.patch(
    "/conferences/{slug:conference_name}/users/{ulid:user_id}/profile",
    response=UserConferenceProfileResponse,
    summary="Update User Conference Profile",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def update_user_conference_profile(
    request: AuthedHttpRequest,
    conference_name: str,
    user_id: ULID,
    payload: PatchDict[UserConferenceProfileSchema],
) -> UserConferenceProfile:
    """Update a user's profile for the given conference."""
    conference = await aget_object_or_404(
        Conference.objects.filter(active=True),
        name=conference_name,
    )
    user = await aget_object_or_404(
        User.objects.filter(is_active=True),
        uid=user_id,
    )

    profile = await ensure_profile(user=user, conference=conference)
    if payload:  # pragma: no branch
        await patch_profile(profile, payload)

        actor = await request.auser()
        logger.info(
            "Conference profile updated by admin.",
            actor=actor,
            user=user,
            conference=conference,
        )
    return await load_profile(profile)
