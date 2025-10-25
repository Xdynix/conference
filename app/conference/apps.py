from django.apps import AppConfig


class ConferenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.conference"

    def ready(self) -> None:
        from app.conference.models import UserProfile
        from app.conference.schemas import Profile
        from app.core.models import User
        from app.core.registry.user_response import user_response_registry

        async def resolve_profile(user: User) -> UserProfile | None:
            return await UserProfile.objects.filter(user=user).afirst()

        user_response_registry.register(
            "profile",
            Profile | None,
            resolver=resolve_profile,
        )
