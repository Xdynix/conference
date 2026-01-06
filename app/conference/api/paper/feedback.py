import hashlib
from operator import itemgetter

from django.shortcuts import aget_object_or_404

from app.conference.models import PaperState
from app.conference.models.review import ReviewState
from app.conference.services import ConferenceService
from app.core.auth import is_authenticated
from app.core.types import AuthedHttpRequest

from .core import router


@router.get(
    "/conferences/{slug:conference_name}/my-papers/{slug:paper_code}/feedbacks",
    response=list[str],
    summary="List My Paper Feedbacks",
    auth=is_authenticated,
)
async def list_my_paper_feedbacks(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> list[str]:
    """Returns anonymized feedbacks for an accepted and announced paper."""
    user = await request.auser()
    conference = await aget_object_or_404(
        await ConferenceService.visible_conferences(user),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        conference.papers.active().filter(owner=user),
        code=paper_code,
    )
    is_accepted = paper.state in (
        PaperState.ACCEPTED,
        PaperState.ACCEPTED_REVISION_NEEDED,
    )
    if not is_accepted or paper.announce_time is None:
        return []

    # Assign each item a deterministic weight based on its PK, then sort by weight.
    # This anonymizes the order while keeping it stable across requests. Unlike
    # shuffling the whole list, adding or removing items only affects their own
    # position, not the relative order of others.
    def weight(item_pk: int) -> int:
        data = f"{paper.pk}:{item_pk}".encode()
        return int.from_bytes(hashlib.sha256(data).digest()[:8])

    feedback: list[tuple[int, str]] = []

    reviews = paper.reviews.filter(state=ReviewState.SUBMITTED)
    async for review in reviews:
        parts = [
            text
            for text in (review.contribution, review.decision_reason, review.comments)
            if text
        ]
        merged = "\n\n".join(parts)
        if merged:
            feedback.append((weight(review.pk), merged))

    admin_comments = paper.admin_comments.all()
    async for comment in admin_comments:
        if comment.content:
            feedback.append((weight(comment.pk), comment.content))

    feedback.sort(key=itemgetter(0))
    return [text for _, text in feedback]
