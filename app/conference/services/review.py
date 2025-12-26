from collections.abc import Collection
from typing import Literal

from django.db.models import QuerySet
from django.utils import timezone
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
from app.conference.models.review import ReviewState
from app.core.models import GlobalRole, User
from app.infra.models import Mutex

from .access import ConferenceAccessService


class AssignerNotAuthorizedError(Exception):
    pass


class ReviewerNotEligibleError(Exception):
    pass


class InvalidReviewStateError(Exception):
    pass


class ReviewSubmissionError(Exception):
    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__(_("Review submission validation failed."))


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

    @classmethod
    def respond_to_assignment(
        cls,
        *,
        review: Review,
        response: Literal[ReviewState.ACCEPTED, ReviewState.DECLINED],
    ) -> Review:
        """Respond to a review assignment, transitioning from Pending to the response.

        Args:
            review: The review to respond to.
            response: Target state, either ACCEPTED or DECLINED.

        Raises:
            ValueError: If response is not ACCEPTED or DECLINED.
            Review.DoesNotExist: If the review's paper, conference, or track has been
                deleted or deactivated.
            InvalidReviewStateError: If the review is not in Pending state.
        """
        if response not in (ReviewState.ACCEPTED, ReviewState.DECLINED):
            raise ValueError(f"Invalid response: {response}.")

        with Mutex.lock_in_transaction(str(review.pk), namespace="review"):
            review = Review.objects.active().get(pk=review.pk)

            if review.state != Review.State.PENDING:
                raise InvalidReviewStateError(
                    _("Review must be in pending state to respond.")
                )

            review.state = response
            review.save(update_fields=["state", "update_time"])

            return review

    @classmethod
    def submit_review(cls, review: Review, *, strict: bool = True) -> Review:
        """Submit a review.

        Validates required fields and transitions the review from Accepted to Submitted
        state.

        Args:
            review: The review to submit.
            strict: If ``True`` (default), validates all required fields including
                scores, contribution, and decision reason. If ``False``, skips
                validation (for admin bypass).

        Raises:
            Review.DoesNotExist: If the review's paper, conference, or track has been
                deleted or deactivated.
            InvalidReviewStateError: If the review is not in Accepted state.
            ReviewSubmissionError: If the review fails field validation. The exception
                contains a list of error dictionaries.
        """
        with Mutex.lock_in_transaction(str(review.pk), namespace="review"):
            review = Review.objects.active().get(pk=review.pk)

            if review.state != Review.State.ACCEPTED:
                raise InvalidReviewStateError(
                    _("Review must be in accepted state to submit.")
                )

            if strict:
                errors: list[dict[str, str]] = []

                score_fields = (
                    "originality",
                    "significance",
                    "technical",
                    "reference",
                    "presentation",
                    "match_topic",
                    "recommendation",
                )
                for field in score_fields:
                    if getattr(review, field) is None:
                        errors.append({field: _("This field is required.")})

                text_fields = ("contribution", "decision_reason")
                for field in text_fields:
                    if not getattr(review, field):
                        errors.append({field: _("This field is required.")})

                if errors:
                    raise ReviewSubmissionError(errors)

            review.state = Review.State.SUBMITTED
            review.submit_time = timezone.now()
            review.save(update_fields=["state", "submit_time", "update_time"])

            return review

    @classmethod
    def unsubmit_review(cls, review: Review) -> Review:
        """Unsubmit a review, returning it to Accepted state for revision.

        Transitions a submitted review back to Accepted state and clears the
        ``submit_time``. This allows the reviewer to make corrections before
        resubmitting.

        Raises:
            Review.DoesNotExist: If the review's paper, conference, or track has been
                deleted or deactivated.
            InvalidReviewStateError: If the review is not in Submitted state or is an
                offline review.
        """
        with Mutex.lock_in_transaction(str(review.pk), namespace="review"):
            review = Review.objects.active().get(pk=review.pk)

            if review.reviewer_id is None:
                raise InvalidReviewStateError(
                    _("Offline reviews cannot be unsubmitted.")
                )

            if review.state != Review.State.SUBMITTED:
                raise InvalidReviewStateError(
                    _("Review must be in submitted state to unsubmit.")
                )

            review.state = Review.State.ACCEPTED
            review.submit_time = None
            review.save(update_fields=["state", "submit_time", "update_time"])

            return review

    @classmethod
    def cancel_review(cls, review: Review) -> Review:
        """Cancel a review assignment.

        Transitions a review to Cancelled state. Can be used for reviews in Pending,
        Accepted, or Submitted states.

        Raises:
            Review.DoesNotExist: If the review's paper, conference, or track has been
                deleted or deactivated.
            InvalidReviewStateError: If the review is not in a cancellable state.
        """
        cancellable_states = {
            Review.State.PENDING,
            Review.State.ACCEPTED,
            Review.State.SUBMITTED,
        }

        with Mutex.lock_in_transaction(str(review.pk), namespace="review"):
            review = Review.objects.active().get(pk=review.pk)

            if review.state not in cancellable_states:
                raise InvalidReviewStateError(
                    _(
                        "Review must be in pending, accepted, "
                        "or submitted state to cancel."
                    )
                )

            review.state = Review.State.CANCELLED
            review.save(update_fields=["state", "update_time"])

            return review

    @classmethod
    def update_review(
        cls,
        review: Review,
        *,
        mode: Literal["admin", "reviewer"] = "reviewer",
        originality: int | None = None,
        significance: int | None = None,
        technical: int | None = None,
        reference: int | None = None,
        presentation: int | None = None,
        match_topic: int | None = None,
        recommendation: int | None = None,
        contribution: str | None = None,
        decision_reason: str | None = None,
        comments: str | None = None,
        confidential_remarks: str | None = None,
    ) -> Review:
        """Update review scores and text fields.

        Updates a review with the provided field values. Only fields that are
        explicitly passed (not ``None``) are modified.

        Args:
            review: The review to update.
            mode: Controls state restrictions. ``"admin"`` allows updates to review
                in Accepted or Submitted state. ``"reviewer"`` allows updates only
                to reviews in Accepted state.
            originality: The originality score.
            significance: The significance score.
            technical: The technical score.
            reference: The reference score.
            presentation: The presentation score.
            match_topic: The match-topic score.
            recommendation: The recommendation score.
            contribution: The contribution content.
            decision_reason: The decision reason content.
            comments: The comments content.
            confidential_remarks: The confidential remarks content.

        Raises:
            Review.DoesNotExist: If the review's paper, conference, or track has been
                deleted or deactivated.
            InvalidReviewStateError: If the review is not in a valid state for the
                given mode.
        """
        if mode == "admin":
            allowed_states = {Review.State.ACCEPTED, Review.State.SUBMITTED}
        else:
            allowed_states = {Review.State.ACCEPTED}

        with Mutex.lock_in_transaction(str(review.pk), namespace="review"):
            review = Review.objects.active().get(pk=review.pk)

            if review.state not in allowed_states:
                if mode == "admin":
                    raise InvalidReviewStateError(
                        _("Review must be in accepted or submitted state to edit.")
                    )
                raise InvalidReviewStateError(
                    _("Review must be in accepted state to save draft.")
                )

            update_fields: list[str] = []

            score_updates = {
                "originality": originality,
                "significance": significance,
                "technical": technical,
                "reference": reference,
                "presentation": presentation,
                "match_topic": match_topic,
                "recommendation": recommendation,
            }
            for field, value in score_updates.items():
                if value is not None:
                    setattr(review, field, value)
                    update_fields.append(field)

            text_updates = {
                "contribution": contribution,
                "decision_reason": decision_reason,
                "comments": comments,
                "confidential_remarks": confidential_remarks,
            }
            for field, content in text_updates.items():
                if content is not None:
                    setattr(review, field, content)
                    update_fields.append(field)

            if update_fields:
                review.save(update_fields=[*update_fields, "update_time"])

            return review
