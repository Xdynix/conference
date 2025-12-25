from collections.abc import Collection

from django.db.models import QuerySet
from django.utils.translation import gettext as _

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    Review,
    TrackRole,
    TrackRoleAssignment,
)
from app.core.models import GlobalRole, User

from .access import ConferenceAccessService


class AssignerNotAuthorizedError(Exception):
    pass


class ReviewerNotEligibleError(Exception):
    pass


class ReviewService:
    @classmethod
    async def visible_reviews(
        cls,
        *,
        conference: Conference,
        user: User,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Review]:
        """Return reviews for the conference visible to the user.

        Visibility rules:

        - Superusers and users with ADMIN/READ_ALL global roles see all reviews.
        - Conference admins (chairs and secretaries) see all reviews.
        - Track admins see only track-level reviews (assignment_level=TRACK) for papers
          in tracks they administer.
        - Other users see no reviews.
        """
        reviews = Review.objects.active().filter(paper__conference=conference)

        ctx = await ConferenceAccessService.context(
            conference=conference,
            user=user,
            global_roles=global_readable,
        )

        if ctx.has_full_conference_scope:
            return reviews

        if not ctx.administered_track_ids:
            return reviews.none()

        return reviews.filter(
            paper__track_id__in=ctx.administered_track_ids,
            assignment_level=Review.AssignmentLevel.TRACK,
        )

    @classmethod
    async def assign_reviewer(
        cls,
        *,
        paper: Paper,
        reviewer: User,
        assigner: User,
    ) -> Review:
        """Assign a reviewer to a paper.

        The assignment level is derived from the assigner's role. Conference admins
        create conference-level assignments; track admins create track-level
        assignments.

        Raises:
            AssignerNotAuthorizedError: If assigner has no admin role.
            ReviewerNotEligibleError: If reviewer has no eligible role or is the
                paper owner.
        """
        if reviewer.pk == paper.owner_id:
            raise ReviewerNotEligibleError(
                _("Paper owner cannot be assigned as reviewer.")
            )

        conference = paper.conference
        ctx = await ConferenceAccessService.context(
            conference=conference,
            user=assigner,
            global_roles=(GlobalRole.ADMIN,),
        )

        if ctx.has_full_conference_scope:
            assignment_level = Review.AssignmentLevel.CONFERENCE
        elif paper.track_id in ctx.administered_track_ids:
            assignment_level = Review.AssignmentLevel.TRACK
        else:
            raise AssignerNotAuthorizedError(
                _("Assigner has no admin role for this paper.")
            )

        if assignment_level == Review.AssignmentLevel.CONFERENCE:
            is_privileged = reviewer.is_superuser or (
                await reviewer.global_role_assignments.filter(
                    role=GlobalRole.ADMIN,
                ).aexists()
            )
            if not is_privileged:
                has_conference_role = await ConferenceRoleAssignment.objects.filter(
                    conference=conference,
                    user=reviewer,
                    role__in=ConferenceRole.reviewers(),
                ).aexists()

                has_track_role = await TrackRoleAssignment.objects.filter(
                    track__conference=conference,
                    user=reviewer,
                    role__in=TrackRole.reviewers(),
                ).aexists()

                if not has_conference_role and not has_track_role:
                    raise ReviewerNotEligibleError(
                        _("Reviewer has no eligible role in the conference.")
                    )
        else:
            has_track_role = await TrackRoleAssignment.objects.filter(
                track_id=paper.track_id,
                user=reviewer,
                role__in=TrackRole.reviewers(),
            ).aexists()

            if not has_track_role:
                raise ReviewerNotEligibleError(
                    _("Reviewer has no eligible role in this track.")
                )

        return await Review.objects.acreate(
            paper=paper,
            reviewer=reviewer,
            state=Review.State.PENDING,
            assigner=assigner,
            assignment_level=assignment_level,
        )
