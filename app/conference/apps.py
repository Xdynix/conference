from collections.abc import Sequence

from django.apps import AppConfig
from pydantic import Field


class ConferenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.conference"

    def ready(self) -> None:
        register_create_user()
        register_search_user()
        register_user_response()


def register_create_user() -> None:
    from app.conference.models import UserProfile
    from app.conference.schemas import Profile
    from app.core.models import User
    from app.core.registry.create_user import create_user_registry

    def create_profile(user: User, payload: Profile) -> None:
        UserProfile.objects.create(
            user=user,
            given_name=payload.given_name,
            family_name=payload.family_name,
            affiliation=payload.affiliation,
            region_code=payload.region_code,
        )

    create_user_registry.register(
        "profile",
        (Profile, Field(default_factory=Profile)),  # type: ignore[arg-type]
        handler=create_profile,
    )


def register_search_user() -> None:
    from app.core.registry.search_user import search_user_registry

    search_user_registry.register(
        "profile__given_name__icontains",
        "profile__family_name__icontains",
        "profile__affiliation__icontains",
    )


def register_user_response() -> None:
    from app.conference.models import UserProfile
    from app.conference.schemas import Profile
    from app.core.models import User
    from app.core.registry.user_response import user_response_registry

    async def resolve_profile(user: User) -> UserProfile | None:
        return await UserProfile.objects.filter(user=user).afirst()

    async def batch_resolve_profile(users: Sequence[User]) -> list[UserProfile | None]:
        user_ids = [user.id for user in users]
        # TODO: Chunk user_ids into batches of ~1000 to avoid SQL parameter limits.
        profiles = UserProfile.objects.filter(user_id__in=user_ids)
        profile_map = {profile.user_id: profile async for profile in profiles}
        return [profile_map.get(user.id) for user in users]

    user_response_registry.register(
        "profile",
        Profile | None,
        resolver=resolve_profile,
        batch_resolver=batch_resolve_profile,
    )
