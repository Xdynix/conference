from http import HTTPStatus
from typing import Annotated

from django.shortcuts import aget_object_or_404
from ninja import Schema, Status
from pydantic import AwareDatetime, StringConstraints
from ulid import ULID

from app.audit.services import audit
from app.audit.types import AuditAction
from app.conference.auth import has_any_conference_roles
from app.conference.models import AdminComment, Conference, ConferenceRole
from app.conference.types import ConferenceUser, ReviewComment
from app.core.auth import has_any_roles
from app.core.models import GlobalRole
from app.core.types import AuthedHttpRequest

from .core import router


class AdminCommentResponse(Schema):
    uid: ULID
    create_time: AwareDatetime
    author: ConferenceUser | None
    content: ReviewComment


class CreateAdminCommentRequest(Schema):
    content: Annotated[
        ReviewComment,
        StringConstraints(min_length=1),
    ]


@router.get(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/admin-comments",
    response=list[AdminCommentResponse],
    summary="List Admin Comments",
    auth=(
        has_any_roles(GlobalRole.ADMIN, GlobalRole.READ_ALL)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def list_admin_comments(
    request: AuthedHttpRequest,  # noqa: ARG001
    conference_name: str,
    paper_code: str,
) -> list[AdminComment]:
    """Returns admin comments for a paper."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    comments = paper.admin_comments.select_related("author__profile").order_by("uid")
    return [comment async for comment in comments]


@router.post(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/admin-comments",
    response={HTTPStatus.CREATED: AdminCommentResponse},
    summary="Create Admin Comment",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def create_admin_comment(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
    payload: CreateAdminCommentRequest,
) -> Status:
    """Creates an admin comment on a paper."""
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )
    paper = await aget_object_or_404(
        conference.papers.active(),
        code=paper_code,
    )

    comment = await AdminComment.objects.acreate(
        paper=paper,
        author=user,
        content=payload.content,
    )

    await audit(
        request=request,
        action=AuditAction.ADMIN_COMMENT_CREATE,
        resource=comment,
        scope=conference.name,
        payload=payload,
    )

    return Status(
        HTTPStatus.CREATED,
        await AdminComment.objects.select_related("author__profile").aget(
            pk=comment.pk
        ),
    )


@router.delete(
    "/conferences/{slug:conference_name}/admin-comments/{ulid:comment_uid}",
    response={HTTPStatus.NO_CONTENT: None},
    summary="Delete Admin Comment",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_roles(*ConferenceRole.admins())
    ),
)
async def delete_admin_comment(
    request: AuthedHttpRequest,
    conference_name: str,
    comment_uid: ULID,
) -> Status:
    """Deletes an admin comment."""
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    comment = await aget_object_or_404(
        AdminComment.objects.filter(paper__conference=conference).select_related(
            "paper", "author"
        ),
        uid=comment_uid,
    )

    await comment.adelete()

    await audit(
        request=request,
        action=AuditAction.ADMIN_COMMENT_DELETE,
        resource=comment,
        scope=conference.name,
    )

    return Status(HTTPStatus.NO_CONTENT, None)
