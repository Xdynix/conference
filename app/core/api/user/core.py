from ninja import Router

from app.core.registry.user_response import user_response_registry

router = Router(tags=["User"], exclude_none=True)


UserResponse = user_response_registry.get_schema()
