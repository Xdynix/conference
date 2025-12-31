"""Temporary workarounds for known library bugs."""


def monkeypatch_django_async_auth() -> None:
    # TODO: Remove after django/django#19709 (Django #36540) released.
    from django.contrib import auth as django_auth

    default_alogin = django_auth.alogin
    default_alogout = django_auth.alogout

    async def alogin(request, user, backend=None):  # type: ignore[no-untyped-def]
        await default_alogin(request, user, backend)
        if hasattr(request, "auser"):

            async def auser():  # type: ignore[no-untyped-def]
                return user

            request.auser = auser

    async def alogout(request):  # type: ignore[no-untyped-def]
        await default_alogout(request)
        if hasattr(request, "auser"):
            from django.contrib.auth.models import AnonymousUser

            async def auser():  # type: ignore[no-untyped-def]
                return AnonymousUser()

            request.auser = auser

    django_auth.alogin = alogin
    django_auth.alogout = alogout


def monkeypatch_django_aupdate_session_auth_hash() -> None:
    # TODO: Remove after django/django#19749 (Django #36561) released.
    from django.contrib import auth as django_auth
    from django.contrib.auth import HASH_SESSION_KEY

    async def aupdate_session_auth_hash(request, user):  # type: ignore[no-untyped-def]
        await request.session.acycle_key()
        if hasattr(user, "get_session_auth_hash") and await request.auser() == user:
            await request.session.aset(HASH_SESSION_KEY, user.get_session_auth_hash())

    django_auth.aupdate_session_auth_hash = aupdate_session_auth_hash


def monkeypatch_django_ninja_openapi_csrf() -> None:
    # TODO: Remove when there is an elegant solution.
    # Django Ninja's OpenAPI documentation page only includes the CSRF token when
    # authentication is configured at the root API level. If authentication is
    # configured only at the router or view level, the CSRF token is omitted, making
    # protected endpoints inaccessible from the OpenAPI documentation interface. This
    # patch forces CSRF token inclusion unconditionally.
    import ninja.openapi.docs

    def _csrf_needed(api) -> bool:  # type: ignore[no-untyped-def]  # noqa: ARG001
        return True

    ninja.openapi.docs._csrf_needed = _csrf_needed


def monkeypatch_django_ninja_openapi_examples() -> None:
    # TODO: Remove after vitalik/django-ninja#1637 released.
    # Django Ninja copies `examples` from JSON Schema (where arrays are valid) to the
    # OpenAPI Parameter Object level (where it must be a map of Example Objects). This
    # causes Swagger UI to fail with "TypeError: i.get is not a function" when rendering
    # parameters with examples. This patch converts the array format to the map format.
    from typing import Any

    import ninja.openapi.schema

    original_class = ninja.openapi.schema.OpenAPISchema

    class OpenAPISchema(original_class):  # type: ignore[misc, valid-type]
        def _extract_parameters(self, model: Any) -> list[dict[str, Any]]:
            result = super()._extract_parameters(model)
            for param in result:
                if "examples" in param and isinstance(param["examples"], list):
                    param["examples"] = {
                        f"example{i}": {"value": v}
                        for i, v in enumerate(param["examples"])
                    }
            return result  # type: ignore[no-any-return]

    ninja.openapi.schema.OpenAPISchema = OpenAPISchema  # type: ignore[misc]


def monkeypatch_django_ninja_patch_dict() -> None:
    # TODO: Remove after vitalik/django-ninja#1592 released.
    # TODO: This patch causes field constraints (minLength, maxLength) to appear twice
    #  in OpenAPI schemas. The `field._copy()` preserves constraints in field metadata
    #  (top level), while `annotation | None` embeds them in the anyOf variant.
    import ninja.patch_dict
    from ninja.patch_dict import (  # type: ignore[attr-defined]
        ModelToDict,
        get_schema_annotations,
        is_optional_type,
    )
    from pydantic import BaseModel

    def create_patch_schema(schema_cls: type[BaseModel]) -> type[ModelToDict]:
        schema_annotations = get_schema_annotations(schema_cls)
        values, annotations = {}, {}

        for name, field in schema_cls.model_fields.items():
            annotation = schema_annotations[name]
            if is_optional_type(annotation):
                continue
            patch_field = field._copy()
            patch_field.default = None
            patch_field.default_factory = None
            values[name] = patch_field
            annotations[name] = annotation | None
        values["__annotations__"] = annotations  # type: ignore[assignment]
        OptionalSchema = type(f"{schema_cls.__name__}Patch", (schema_cls,), values)

        class OptionalDictSchema(ModelToDict):
            _wrapped_model = OptionalSchema
            _wrapped_model_dump_params = {"exclude_unset": True}  # noqa: RUF012

        return OptionalDictSchema

    ninja.patch_dict.create_patch_schema = create_patch_schema
