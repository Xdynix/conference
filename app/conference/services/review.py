from collections.abc import Collection, Sequence
from enum import StrEnum
from typing import Literal, Self

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from loguru import logger
from pydantic import BaseModel, ConfigDict
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    PaperState,
    Review,
    ReviewerNotificationLog,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.models.review import ReviewAssignmentLevel, ReviewState
from app.core.models import GlobalRole, User
from app.infra.models import Mutex
from app.utils.email import EmailContext, EmailTemplate

from .access import ConferenceAccessService
from .paper import PaperStateError, PaperWithdrawnError


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
            assignment_level=ReviewAssignmentLevel.TRACK,
        )

    @classmethod
    def assign_reviewer(
        cls,
        *,
        paper: Paper,
        reviewer: User,
        assigner: User,
        mode: Literal["conference", "track"],
    ) -> Review:
        """Assign a reviewer to a paper.

        Validates that the paper is in a valid state for review assignment, transitions
        the paper from Submitted to Under Review if needed, and creates a review
        assignment.

        Args:
            paper: The paper to assign a reviewer to.
            reviewer: The user to assign as reviewer.
            assigner: The user performing the assignment.
            mode: Assignment mode. ``"conference"`` creates conference-level assignments
                and allows reviewers with any conference or track role. ``"track"``
                creates track-level assignments and only allows reviewers with a role
                in the paper's track.

        Raises:
            Paper.DoesNotExist: If the paper, its conference, or its track has been
                deleted or deactivated.
            PaperWithdrawnError: If the paper has been withdrawn.
            PaperStateError: If the paper is in Draft state or has been decided and
                announced.
            ReviewerNotEligibleError: If reviewer has no eligible role.
        """
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper = Paper.objects.active().get(pk=paper.pk)

            if paper.withdraw_time is not None:
                raise PaperWithdrawnError(
                    _("Cannot assign reviewers to withdrawn papers.")
                )
            if paper.state == PaperState.DRAFT:
                raise PaperStateError(
                    _("Cannot assign reviewers to papers in Draft state.")
                )
            if paper.announce_time is not None and paper.state in PaperState.decided():
                raise PaperStateError(
                    _("Cannot assign reviewers to papers after decision announcement.")
                )

            if mode == "conference":
                assignment_level = ReviewAssignmentLevel.CONFERENCE
                is_privileged = reviewer.is_superuser or (
                    reviewer.global_role_assignments.filter(
                        role=GlobalRole.ADMIN,
                    ).exists()
                )
                if not is_privileged:
                    has_conference_role = ConferenceRoleAssignment.objects.filter(
                        conference_id=paper.conference_id,
                        user=reviewer,
                        role__in=ConferenceRole.reviewers(),
                    ).exists()

                    has_track_role = TrackRoleAssignment.objects.filter(
                        track__conference_id=paper.conference_id,
                        user=reviewer,
                        role__in=TrackRole.reviewers(),
                    ).exists()

                    if not has_conference_role and not has_track_role:
                        raise ReviewerNotEligibleError(
                            _("Reviewer has no eligible role in the conference.")
                        )
            else:
                assignment_level = ReviewAssignmentLevel.TRACK
                has_track_role = TrackRoleAssignment.objects.filter(
                    track_id=paper.track_id,
                    user=reviewer,
                    role__in=TrackRole.reviewers(),
                ).exists()

                if not has_track_role:
                    raise ReviewerNotEligibleError(
                        _("Reviewer has no eligible role in this track.")
                    )

            if paper.state == PaperState.SUBMITTED:
                paper.state = PaperState.UNDER_REVIEW
                paper.save(update_fields=["state", "update_time"])

            return Review.objects.create(
                paper=paper,
                reviewer=reviewer,
                state=ReviewState.PENDING,
                assigner=assigner,
                assignment_level=assignment_level,
            )

    @classmethod
    def respond_to_assignment(
        cls,
        review: Review,
        *,
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

            if review.state != ReviewState.PENDING:
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

            if review.state != ReviewState.ACCEPTED:
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

            review.state = ReviewState.SUBMITTED
            review.submit_time = timezone.now()
            review.save(update_fields=["state", "submit_time", "update_time"])

            return review

    @classmethod
    def unsubmit_review(
        cls,
        review: Review,
        *,
        mode: Literal["conference", "track"],
    ) -> Review:
        """Unsubmit a review, returning it to Accepted state for revision.

        Transitions a submitted review back to Accepted state and clears the
        ``submit_time``. This allows the reviewer to make corrections before
        resubmitting.

        Args:
            review: The review to unsubmit.
            mode: Caller's scope. ``"conference"`` allows unsubmit regardless of
                paper state. ``"track"`` blocks unsubmit after decision announcement.

        Raises:
            Review.DoesNotExist: If the review's paper, conference, or track has been
                deleted or deactivated.
            InvalidReviewStateError: If the review is not in Submitted state, is an
                offline review, or if mode is ``"track"`` and the paper decision has
                been announced.
        """
        with Mutex.lock_in_transaction(str(review.pk), namespace="review"):
            review = Review.objects.active().select_related("paper").get(pk=review.pk)

            if review.reviewer_id is None:
                raise InvalidReviewStateError(
                    _("Offline reviews cannot be unsubmitted.")
                )

            if review.state != ReviewState.SUBMITTED:
                raise InvalidReviewStateError(
                    _("Review must be in submitted state to unsubmit.")
                )

            if mode == "track" and review.paper.announce_time is not None:
                raise InvalidReviewStateError(
                    _("Cannot unsubmit reviews for papers after decision announcement.")
                )

            review.state = ReviewState.ACCEPTED
            review.submit_time = None
            review.save(update_fields=["state", "submit_time", "update_time"])

            return review

    @classmethod
    def cancel_review(
        cls,
        review: Review,
        *,
        mode: Literal["conference", "track"],
    ) -> Review:
        """Cancel a review assignment.

        Transitions a review to Cancelled state. Can be used for reviews in Pending,
        Accepted, or Submitted states.

        Args:
            review: The review to cancel.
            mode: Caller's scope. ``"conference"`` allows cancellation regardless of
                paper state. ``"track"`` blocks cancellation after decision
                announcement.

        Raises:
            Review.DoesNotExist: If the review's paper, conference, or track has been
                deleted or deactivated.
            InvalidReviewStateError: If the review is not in a cancellable state, or
                if mode is ``"track"`` and the paper decision has been announced.
        """
        cancellable_states = {
            ReviewState.PENDING,
            ReviewState.ACCEPTED,
            ReviewState.SUBMITTED,
        }

        with Mutex.lock_in_transaction(str(review.pk), namespace="review"):
            review = Review.objects.active().select_related("paper").get(pk=review.pk)

            if review.state not in cancellable_states:
                raise InvalidReviewStateError(
                    _(
                        "Review must be in pending, accepted, "
                        "or submitted state to cancel."
                    )
                )

            if mode == "track" and review.paper.announce_time is not None:
                raise InvalidReviewStateError(
                    _("Cannot cancel reviews for papers after decision announcement.")
                )

            review.state = ReviewState.CANCELLED
            review.save(update_fields=["state", "update_time"])

            return review

    @classmethod
    def update_review(
        cls,
        review: Review,
        *,
        mode: Literal["admin", "reviewer"],
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
            allowed_states = {ReviewState.ACCEPTED, ReviewState.SUBMITTED}
        else:
            allowed_states = {ReviewState.ACCEPTED}

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


class ReviewerNotificationContext(EmailContext):
    """Template context for reviewer notification emails."""

    site_name: str
    conference_name: str
    conference_display_name: str
    given_name: str
    family_name: str
    affiliation: str
    pending_review_count: int
    accepted_review_count: int

    @classmethod
    def sample(cls) -> Self:
        return cls(
            site_name=settings.SITE_NAME,
            conference_name="CONF-2025",
            conference_display_name="Sample Conference 2025",
            given_name="John",
            family_name="Doe",
            affiliation="Sample University",
            pending_review_count=3,
            accepted_review_count=1,
        )


class SendNotificationStatus(StrEnum):
    SENT = "sent"
    SKIPPED = "skipped"
    NOT_FOUND = "not_found"
    FAILED = "failed"


class SendNotificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    reviewer: ULID
    status: SendNotificationStatus
    reviewer_email: str | None = None
    reason: str | None = None


class ReviewerNotificationService:
    @classmethod
    def send_notification(
        cls,
        conference: Conference,
        reviewer_uid: ULID,
        *,
        template: EmailTemplate,
        reply_to: str | None = None,
        force_send_to_recent: bool = False,
    ) -> tuple[bool, str]:
        """Send a notification email to a reviewer and update tracking.

        Returns:
            Tuple of ``(sent, reviewer_email)`` where ``sent`` is ``True`` if email was
            sent, ``False`` if skipped (no actionable reviews or rate limited).

        Raises:
            User.DoesNotExist: If the user is not found.
        """
        with Mutex.lock_in_transaction(
            f"{conference.pk}:{reviewer_uid}",
            namespace="reviewer_notification",
        ):
            reviewer = (
                User.objects.active().select_related("profile").get(uid=reviewer_uid)
            )

            counts = (
                Review.objects.active()
                .filter(
                    paper__conference=conference,
                    reviewer=reviewer,
                    state__in=[ReviewState.PENDING, ReviewState.ACCEPTED],
                )
                .aggregate(
                    pending_review_count=Count(
                        "pk",
                        filter=Q(state=ReviewState.PENDING),
                    ),
                    accepted_review_count=Count(
                        "pk",
                        filter=Q(state=ReviewState.ACCEPTED),
                    ),
                )
            )
            pending_review_count: int = counts["pending_review_count"]
            accepted_review_count: int = counts["accepted_review_count"]

            if pending_review_count == 0 and accepted_review_count == 0:
                return False, reviewer.email

            now = timezone.now()
            log = ReviewerNotificationLog.objects.filter(
                conference=conference,
                reviewer=reviewer,
            ).first()
            if (
                log is not None
                and (now - log.last_notification_time)
                <= settings.REVIEWER_NOTIFICATION_EMAIL_INTERVAL
                and not force_send_to_recent
            ):
                return False, reviewer.email

            profile = getattr(reviewer, "profile", None)
            context = ReviewerNotificationContext(
                site_name=settings.SITE_NAME,
                conference_name=conference.name,
                conference_display_name=conference.display_name,
                given_name=profile.given_name if profile else "",
                family_name=profile.family_name if profile else "",
                affiliation=profile.affiliation if profile else "",
                pending_review_count=pending_review_count,
                accepted_review_count=accepted_review_count,
            )
            rendered = template.render(context)
            email_message = rendered.build_message(
                to=reviewer.email,
                reply_to=reply_to or (),
            )

            if log is not None:
                log.last_notification_time = now
                log.save(update_fields=["last_notification_time"])
            else:
                ReviewerNotificationLog.objects.create(
                    conference=conference,
                    reviewer=reviewer,
                    last_notification_time=now,
                )

            transaction.on_commit(email_message.send)

            return True, reviewer.email

    @classmethod
    def send_notifications(
        cls,
        conference: Conference,
        reviewer_uids: Sequence[ULID],
        *,
        template: EmailTemplate,
        reply_to: str | None = None,
        force_send_to_recent: bool = False,
    ) -> list[SendNotificationResult]:
        """Send notification emails to multiple reviewers.

        Each reviewer is processed in its own transaction. Failures are isolated and
        do not affect other reviewers.
        """
        results: list[SendNotificationResult] = []

        for uid in reviewer_uids:
            try:
                sent, reviewer_email = cls.send_notification(
                    conference,
                    uid,
                    template=template,
                    reply_to=reply_to,
                    force_send_to_recent=force_send_to_recent,
                )
            except User.DoesNotExist:
                results.append(
                    SendNotificationResult(
                        reviewer=uid,
                        status=SendNotificationStatus.NOT_FOUND,
                        reason=_("Reviewer not found."),
                    )
                )
            except Exception:
                logger.exception(
                    "Unknown error when sending reviewer notification.",
                    reviewer_uid=uid,
                )
                results.append(
                    SendNotificationResult(
                        reviewer=uid,
                        status=SendNotificationStatus.FAILED,
                        reason=_("An unexpected error has occurred."),
                    )
                )
            else:
                if sent:
                    results.append(
                        SendNotificationResult(
                            reviewer=uid,
                            status=SendNotificationStatus.SENT,
                            reviewer_email=reviewer_email,
                        )
                    )
                else:
                    results.append(
                        SendNotificationResult(
                            reviewer=uid,
                            status=SendNotificationStatus.SKIPPED,
                            reviewer_email=reviewer_email,
                            reason=_(
                                "Skipped due to no actionable reviews or rate limiting."
                            ),
                        )
                    )

        return results
