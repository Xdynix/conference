from collections.abc import Collection

from django.db.models import QuerySet

from app.conference.models import Conference, Review
from app.core.models import GlobalRole, User

from .access import ConferenceAccessService


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
