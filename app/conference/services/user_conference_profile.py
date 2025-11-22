from collections.abc import Collection

from app.conference.models import Conference, UserConferenceProfile
from app.conference.services import KeywordService
from app.core.models import User


class UserConferenceProfileService:
    @classmethod
    async def get_or_create_profile(
        cls,
        *,
        user: User,
        conference: Conference,
    ) -> UserConferenceProfile:
        """Get or create a user's profile for a conference."""
        profile, _ = await UserConferenceProfile.objects.aget_or_create(
            user=user,
            conference=conference,
        )
        return profile

    @classmethod
    async def load_profile_with_keywords(
        cls,
        profile: UserConferenceProfile,
    ) -> UserConferenceProfile:
        """Load a profile with prefetched interested keywords."""
        return await UserConferenceProfile.objects.prefetch_related(
            "interested_keywords"
        ).aget(pk=profile.pk)

    @classmethod
    async def update_profile(
        cls,
        *,
        profile: UserConferenceProfile,
        desired_paper_count: int | None = None,
        interested_keywords: Collection[str] | None = None,
    ) -> None:
        """Update a user's conference profile with validated fields.

        Raises:
            ValueError: If keyword validation fails.
        """
        # No transaction needed: Updates are not atomic across both fields, but
        # for user preference data the risk of partial updates is acceptable.
        # Keyword validation occurs before any writes to minimize failure risk.

        # Validate `keywords` if provided.
        validated_keywords = await KeywordService.validate_keyword_texts(
            interested_keywords
        )

        # Update `desired_paper_count` if provided.
        if desired_paper_count is not None:
            profile.desired_paper_count = desired_paper_count
            await profile.asave(update_fields=["desired_paper_count", "update_time"])

        # Update keywords if provided.
        if validated_keywords is not None:
            await profile.interested_keywords.aset(validated_keywords)
