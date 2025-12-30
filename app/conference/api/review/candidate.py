from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import aget_object_or_404
from ninja import Schema

from app.conference.auth import has_any_conference_or_track_roles
from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Review,
    TrackRole,
    TrackRoleAssignment,
    UserConferenceProfile,
)
from app.conference.models.review import ReviewState
from app.conference.services import PaperService
from app.conference.services.access import ConferenceAccessService
from app.conference.types import ConferenceUser
from app.core.auth import has_any_roles
from app.core.models import GlobalRole, User
from app.core.types import AuthedHttpRequest

from .core import router


class ReviewerWorkload(Schema):
    pending_count: int = 0
    accepted_count: int = 0
    submitted_count: int = 0
    desired_count: int = 0


class ReviewerResponse(ConferenceUser):
    workload: ReviewerWorkload
    has_declined: bool = False
    match_score: int = 0

    @staticmethod
    def resolve_workload(user: User) -> ReviewerWorkload:
        return ReviewerWorkload(
            pending_count=user.pending_count,  # type: ignore[attr-defined]
            accepted_count=user.accepted_count,  # type: ignore[attr-defined]
            submitted_count=user.submitted_count,  # type: ignore[attr-defined]
            desired_count=user.desired_count,  # type: ignore[attr-defined]
        )


@router.get(
    "/conferences/{slug:conference_name}/papers/{slug:paper_code}/reviewer-candidates",
    response=list[ReviewerResponse],
    summary="List Reviewer Candidates",
    auth=(
        has_any_roles(GlobalRole.ADMIN)
        | has_any_conference_or_track_roles(
            *ConferenceRole.admins(),
            *TrackRole.admins(),
        )
    ),
)
async def list_reviewer_candidates(
    request: AuthedHttpRequest,
    conference_name: str,
    paper_code: str,
) -> list[User]:
    """Returns potential reviewers for a paper based on the requester's role.

    Conference admins see all eligible users in the conference. Track admins see only
    users with reviewer roles in the paper's track. Excludes the requester, the paper
    owner, and users who already have an active review for this paper.
    """
    user = await request.auser()
    conference = await aget_object_or_404(
        Conference.objects.active(),
        name=conference_name,
    )

    paper = await aget_object_or_404(
        await PaperService.visible_papers(conference, user),
        code=paper_code,
    )

    active_reviewers = Review.objects.filter(
        paper=paper,
        reviewer_id=OuterRef("pk"),
        state__in=ReviewState.active(),
    )
    declined_review = Review.objects.filter(
        paper=paper,
        reviewer_id=OuterRef("pk"),
        state=ReviewState.DECLINED,
    )

    def workload_count(state: ReviewState) -> Coalesce:
        return Coalesce(
            Subquery(
                Review.objects.active()
                .filter(
                    paper__conference=conference,
                    reviewer_id=OuterRef("pk"),
                    state=state,
                )
                .values("reviewer_id")
                .annotate(c=Count("pk"))
                .values("c")
            ),
            0,
            output_field=IntegerField(),
        )

    candidates = (
        User.objects.active()
        .exclude(pk=paper.owner_id)
        .exclude(pk=user.pk)
        .exclude(Exists(active_reviewers))
        .annotate(
            pending_count=workload_count(ReviewState.PENDING),
            accepted_count=workload_count(ReviewState.ACCEPTED),
            submitted_count=workload_count(ReviewState.SUBMITTED),
            has_declined=Exists(declined_review),
        )
    )

    ctx = await ConferenceAccessService.context(
        conference=conference,
        user=user,
        global_roles=(GlobalRole.ADMIN,),
    )
    if ctx.has_full_conference_scope:
        conference_role_users = ConferenceRoleAssignment.objects.filter(
            conference=conference,
            user_id=OuterRef("pk"),
            role__in=ConferenceRole.reviewers(),
        )
        track_role_users = TrackRoleAssignment.objects.filter(
            track__conference=conference,
            user_id=OuterRef("pk"),
            role__in=TrackRole.reviewers(),
        )
        global_admin_users = User.objects.filter(
            pk=OuterRef("pk"),
        ).filter(
            Q(is_superuser=True) | Q(global_role_assignment__role=GlobalRole.ADMIN)
        )

        candidates = candidates.filter(
            Q(Exists(conference_role_users))
            | Q(Exists(track_role_users))
            | Q(Exists(global_admin_users))
        )

    elif paper.track_id in ctx.administered_track_ids:  # pragma: no branch
        track_role_users = TrackRoleAssignment.objects.filter(
            track_id=paper.track_id,
            user_id=OuterRef("pk"),
            role__in=TrackRole.reviewers(),
        )

        candidates = candidates.filter(Exists(track_role_users))

    else:
        raise AssertionError(
            "Unreachable: auth passed but no access scope."
        )  # pragma: no cover

    candidates_list = [
        candidate
        async for candidate in candidates.select_related("profile").order_by("uid")
    ]

    paper_keywords = {k.pk async for k in paper.keywords.all()}
    profiles: dict[int, tuple[set[int], int]] = {}
    async for p in UserConferenceProfile.objects.filter(
        user_id__in=[c.pk for c in candidates_list],
        conference=conference,
    ).prefetch_related("interested_keywords"):
        keywords = {k.pk for k in p.interested_keywords.all()}
        profiles[p.user_id] = (keywords, p.desired_paper_count)

    for candidate in candidates_list:
        user_keywords, desired_count = profiles.get(candidate.pk, (set(), 0))
        candidate.match_score = len(paper_keywords & user_keywords)  # type: ignore[attr-defined]
        candidate.desired_count = desired_count  # type: ignore[attr-defined]

    return candidates_list
