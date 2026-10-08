"""Temporary workarounds for known library bugs."""


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

    from ninja.openapi.schema import OpenAPISchema

    original = OpenAPISchema._extract_parameters

    def _extract_parameters(self: OpenAPISchema, model: Any) -> list[dict[str, Any]]:
        result = original(self, model)
        for param in result:
            if isinstance(param.get("examples"), list):
                param["examples"] = {
                    f"example{i}": {"value": v} for i, v in enumerate(param["examples"])
                }
        return result

    OpenAPISchema._extract_parameters = _extract_parameters  # type: ignore[method-assign]


def monkeypatch_django_ninja_patch_dict() -> None:
    # TODO: Remove after vitalik/django-ninja#1592 released.
    # Django Ninja's `PatchDict` rebuilds each field from the class annotation and a
    # bare `None` default, discarding `Field` constraints (minLength, maxLength, ge,
    # etc.) and validators. This patch copies the original `FieldInfo` instead. It
    # pairs the copy with the bare `field.annotation`, not the class annotation,
    # because the copy already carries the `Annotated` metadata; using both would
    # duplicate constraints in the OpenAPI schema.
    from typing import Any

    import ninja.patch_dict
    from ninja.patch_dict import ModelToDict
    from ninja.utils import is_optional_type
    from pydantic import BaseModel

    def create_patch_schema(schema_cls: type[BaseModel]) -> type[ModelToDict]:
        values, annotations = {}, {}

        for name, field in schema_cls.model_fields.items():
            annotation: Any = field.annotation
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
