import json
from http import HTTPStatus

import httpx
from django.shortcuts import aget_object_or_404
from django.utils.translation import gettext as _
from loguru import logger
from ninja import PatchDict, Schema
from ninja.errors import HttpError
from pydantic import Field
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    IEEEeCopyrightConfig,
    IEEEeCopyrightConsent,
    Track,
)
from app.conference.types import IEEEeCopyrightConfig as BaseIEEEeCopyrightConfigSchema
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest
from app.ninja.errors import ErrorResponse, make_validation_error

from .core import router


class IEEEeCopyrightConfigSchema(BaseIEEEeCopyrightConfigSchema):
    exempt_tracks: list[ULID] = Field(default_factory=list, max_length=1_000)


class IEEEeCopyrightConfigResponse(IEEEeCopyrightConfigSchema):
    @staticmethod
    def resolve_exempt_tracks(
        ieee_ecopyright_config: IEEEeCopyrightConfig,
    ) -> list[ULID]:
        return [track.uid for track in ieee_ecopyright_config.exempt_tracks.all()]


@router.get(
    "/conferences/{slug:conference_name}/ieee-ecopyright-config",
    response=IEEEeCopyrightConfigResponse,
    summary="Get IEEE eCopyright Config",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def get_ieee_ecopyright_config(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
) -> IEEEeCopyrightConfig:
    """Retrieve the IEEE eCopyright configuration for a conference.

    Returns 404 if no configuration exists.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    return await aget_object_or_404(
        IEEEeCopyrightConfig.objects.prefetch_related("exempt_tracks"),
        conference=conference,
    )


@router.patch(
    "/conferences/{slug:conference_name}/ieee-ecopyright-config",
    response=IEEEeCopyrightConfigResponse,
    summary="Update IEEE eCopyright Config",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def update_ieee_ecopyright_config(
    request: AuthedHttpRequest,
    conference_name: str,
    payload: PatchDict[IEEEeCopyrightConfigSchema],
) -> IEEEeCopyrightConfig:
    """Create or update the IEEE eCopyright configuration for a conference.

    When creating a new configuration, ``publication_title`` and ``article_source`` are
    required. When updating an existing configuration, all fields are optional and only
    provided fields are modified.

    Track UIDs in ``exempt_tracks`` are validated to ensure they belong to the
    conference.
    """
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    config = await IEEEeCopyrightConfig.objects.filter(conference=conference).afirst()

    if config is None:
        missing = []
        if "publication_title" not in payload:
            missing.append("publication_title")
        if "article_source" not in payload:
            missing.append("article_source")
        if missing:
            message = _("Required fields missing: %(fields)s") % {
                "fields": ", ".join(missing)
            }
            raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, message)

    tracks_to_set: list[Track] | None = None
    if "exempt_tracks" in payload:
        track_uids = payload["exempt_tracks"]
        if track_uids:
            tracks_to_set = [
                track
                async for track in Track.objects.filter(
                    conference=conference,
                    uid__in=track_uids,
                )
            ]
            valid_uids = {track.uid for track in tracks_to_set}
            invalid_uids = [str(uid) for uid in track_uids if uid not in valid_uids]
            if invalid_uids:
                message = _("Invalid track UIDs: %(uids)s") % {
                    "uids": ", ".join(invalid_uids)
                }
                raise make_validation_error(path="exempt_tracks", message=message)
        else:
            tracks_to_set = []

    if config is None:
        config = await IEEEeCopyrightConfig.objects.acreate(
            conference=conference,
            publication_title=payload["publication_title"],
            article_source=payload["article_source"],
        )
    else:
        update_fields = []
        if "publication_title" in payload:
            config.publication_title = payload["publication_title"]
            update_fields.append("publication_title")
        if "article_source" in payload:
            config.article_source = payload["article_source"]
            update_fields.append("article_source")
        if update_fields:
            await config.asave(update_fields=update_fields)

    if tracks_to_set is not None:
        if tracks_to_set:
            await config.exempt_tracks.aset(tracks_to_set)
        else:
            await config.exempt_tracks.aclear()

    await audit(
        request=request,
        action=AuditAction.CONFERENCE_UPDATE_ECOPYRIGHT_CONFIG,
        resource=conference,
        scope=conference.name,
        payload=payload,
    )

    return await IEEEeCopyrightConfig.objects.prefetch_related("exempt_tracks").aget(
        pk=config.pk
    )


IEEE_ECOPYRIGHT_API_URL = (
    "https://conferences.ieee.org/ecfregform/pubsecfarticles/{article_source}"
)
IEEE_ECOPYRIGHT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)


class RefreshIEEEeCopyrightConsentsResponse(Schema):
    unmatched_codes: list[str]


@router.post(
    "/conferences/{slug:conference_name}/ieee-ecopyright-consents:refresh",
    response={
        HTTPStatus.OK: RefreshIEEEeCopyrightConsentsResponse,
        HTTPStatus.BAD_REQUEST: ErrorResponse,
        HTTPStatus.BAD_GATEWAY: ErrorResponse,
    },
    summary="Refresh IEEE eCopyright Consents",
    auth=(
        has_any_roles(GlobalRole.ADMIN) | has_any_conference_roles(ConferenceRole.CHAIR)
    ),
)
async def refresh_ieee_ecopyright_consents(
    request: AuthedHttpRequest,
    conference_name: str,
) -> RefreshIEEEeCopyrightConsentsResponse:
    """Fetch eCopyright consent status from IEEE and create local consent records.

    Matches articles from IEEE by paper code and creates consent records for papers
    that don't already have one. Returns a list of article codes from IEEE that have
    no matching paper in the system.

    IEEE applies rate limiting to this endpoint. Avoid calling too frequently.
    """
    # We assume the IEEE response is immutable and complete: once a consent appears in
    # the response, it won't change or disappear. This means we only create records and
    # never update or delete them based on IEEE data.
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    config = await IEEEeCopyrightConfig.objects.filter(conference=conference).afirst()
    if config is None:
        raise HttpError(
            HTTPStatus.BAD_REQUEST,
            _("Conference has no IEEE eCopyright configuration."),
        )

    url = IEEE_ECOPYRIGHT_API_URL.format(article_source=config.article_source)
    try:
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=2),
            timeout=30,
            headers={"User-Agent": IEEE_ECOPYRIGHT_USER_AGENT},
        ) as client:
            response = await client.get(url)
        response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning(
            "IEEE eCopyright API request failed.",
            error=str(exc),
            conference=conference_name,
        )
        raise HttpError(
            HTTPStatus.BAD_GATEWAY,
            _("IEEE eCopyright API request failed."),
        ) from exc

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        logger.warning(
            "IEEE eCopyright API returned invalid JSON.",
            conference=conference_name,
        )
        raise HttpError(
            HTTPStatus.BAD_GATEWAY,
            _("IEEE eCopyright API returned invalid response."),
        ) from exc

    if data.get("status") != "Success":
        logger.warning(
            "IEEE eCopyright API returned non-success status.",
            status=data.get("status"),
            conference=conference_name,
        )
        raise HttpError(
            HTTPStatus.BAD_GATEWAY,
            _("IEEE eCopyright API returned an error."),
        )

    try:
        articles = data.get("articleList", [])
        article_by_code = {article["ecfPaperId"]: article for article in articles}
        codes = list(article_by_code)
    except (KeyError, TypeError) as exc:
        logger.exception(
            "IEEE eCopyright API returned unexpected format.",
            conference=conference_name,
        )
        raise HttpError(
            HTTPStatus.BAD_GATEWAY,
            _("IEEE eCopyright API returned unexpected format."),
        ) from exc

    papers = {
        paper.code: paper async for paper in conference.papers.filter(code__in=codes)
    }
    existing_consent_paper_ids = {
        consent.paper_id
        async for consent in IEEEeCopyrightConsent.objects.filter(
            paper__in=papers.values()
        )
    }

    consents_to_create = []
    for code, paper in papers.items():
        if paper.pk not in existing_consent_paper_ids:
            consents_to_create.append(
                IEEEeCopyrightConsent(
                    paper=paper,
                    raw_response=article_by_code[code],
                )
            )

    if consents_to_create:
        await IEEEeCopyrightConsent.objects.abulk_create(consents_to_create)

    unmatched_codes = [code for code in codes if code not in papers]

    await audit(
        request=request,
        action=AuditAction.CONFERENCE_REFRESH_ECOPYRIGHT_CONSENTS,
        resource=conference,
        scope=conference.name,
        detail={
            "created_count": len(consents_to_create),
            "unmatched_count": len(unmatched_codes),
        },
    )

    return RefreshIEEEeCopyrightConsentsResponse(unmatched_codes=unmatched_codes)
