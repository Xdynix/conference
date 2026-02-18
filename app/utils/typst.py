__all__ = (
    "CompilationError",
    "TypstError",
    "compile_template",
    "typst_json_default",
)

import json
import tempfile
from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, overload
from uuid import UUID

import typst
from pydantic import HttpUrl
from ulid import ULID


def typst_json_default(obj: Any) -> Any:
    """Serialize common types for typst ``sys_inputs`` JSON.

    Datetimes and dates are serialized as component dicts (``year``, ``month``, ``day``,
    ``hour``, ``minute``, ``second``) matching the parameters of typst's ``datetime``
    constructor. Templates can reconstruct a typst datetime and format it with
    ``.display()``::

        #let d = datetime(..json(bytes(sys.inputs.at("data"))).submit_time)
        Submitted on #d.display("[month repr:long] [day], [year]")

    Timezone-aware datetimes are rejected because typst's ``datetime`` has no timezone
    support; silently dropping timezone info could cause miscommunication in formal
    documents. Callers should convert to naive local time before serialization.

    Decimals are serialized as strings to preserve exact precision. ``ULID``, ``UUID``,
    and ``HttpUrl`` are also serialized as strings.

    Callers can extend this by wrapping it in a custom default function::

        def my_default(obj):
            if isinstance(obj, MyType):
                return ...
            return typst_json_default(obj)

        compile_template(template, data, json_default=my_default)
    """
    match obj:
        case datetime(tzinfo=tz) if tz is not None:
            raise ValueError(
                f"Timezone-aware datetime {obj!r} cannot be serialized for typst. "
                "Convert to naive local time first."
            )
        case datetime():
            return {
                "year": obj.year,
                "month": obj.month,
                "day": obj.day,
                "hour": obj.hour,
                "minute": obj.minute,
                "second": obj.second,
            }
        case date():
            return {"year": obj.year, "month": obj.month, "day": obj.day}
        case time(tzinfo=tz) if tz is not None:
            raise ValueError(
                f"Timezone-aware time {obj!r} cannot be serialized for typst. "
                "Convert to naive local time first."
            )
        case time():
            return {"hour": obj.hour, "minute": obj.minute, "second": obj.second}
        case Decimal() | ULID() | UUID() | HttpUrl():
            return str(obj)
        case _:  # pragma: no cover
            raise TypeError(f"Object of type {type(obj).__name__} is not serializable.")


class TypstError(Exception):
    """Base exception for all typst compilation errors."""


class CompilationError(TypstError):
    """Typst compiler rejected the template (syntax error, undefined variable, etc.).

    Attributes:
        diagnostic: Formatted compiler output with source pointers (line numbers,
            carets).
        hints: Compiler suggestions, if any.
    """

    diagnostic: str
    hints: list[str]

    def __init__(
        self,
        message: str,
        *,
        diagnostic: str = "",
        hints: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic
        self.hints = hints or []


@overload
def compile_template(
    template: str | bytes,
    data: dict[str, Any],
    *,
    output: str | Path,
    files: dict[str, bytes] | None = None,
    font_paths: list[str | Path] | None = None,
    json_default: Callable[[Any], Any] = typst_json_default,
    validate_only: Literal[False] = False,
) -> None: ...


@overload
def compile_template(
    template: str | bytes,
    data: dict[str, Any],
    *,
    output: None = None,
    files: dict[str, bytes] | None = None,
    font_paths: list[str | Path] | None = None,
    json_default: Callable[[Any], Any] = typst_json_default,
    validate_only: Literal[True],
) -> None: ...


@overload
def compile_template(
    template: str | bytes,
    data: dict[str, Any],
    *,
    output: None = None,
    files: dict[str, bytes] | None = None,
    font_paths: list[str | Path] | None = None,
    json_default: Callable[[Any], Any] = typst_json_default,
    validate_only: Literal[False] = False,
) -> bytes: ...


def compile_template(
    template: str | bytes,
    data: dict[str, Any],
    *,
    output: str | Path | None = None,
    files: dict[str, bytes] | None = None,
    font_paths: list[str | Path] | None = None,
    json_default: Callable[[Any], Any] = typst_json_default,
    validate_only: bool = False,
) -> bytes | None:
    """Compile a typst template with data, returning or writing PDF bytes.

    The template source is combined with *files* into a virtual filesystem. *data* is
    JSON-serialized and passed via ``sys_inputs`` so templates access it with
    ``json(bytes(sys.inputs.at("data")))``. Pass *json_default* to handle types that
    ``json.dumps`` cannot serialize natively (e.g., ``Decimal``, ``ULID``).

    Pass *font_paths* to make additional font directories available to the compiler.
    Custom fonts are discovered regardless of ``ignore_system_fonts``; the flag only
    controls system font scanning.

    Three modes of operation, selected by the keyword arguments:

    - **Return bytes** (default): Returns the PDF as ``bytes``.
    - **Write to path** (``output=<path>``): Writes the PDF to *output* and returns
      ``None``.
    - **Validate only** (``validate_only=True``): Checks that the template compiles
      without producing PDF output. Returns ``None``.

    This function is synchronous. Async callers should wrap it with a timeout to guard
    against resource exhaustion from malicious templates::

        await asyncio.wait_for(
            asyncio.to_thread(compile_template, template, data),
            timeout=5.0,
        )

    Raises:
        CompilationError: The typst compiler rejected the template.
    """
    if validate_only and output is not None:
        raise ValueError("`validate_only=True` and `output` are mutually exclusive.")

    if files is not None:
        if "main.typ" in files:
            raise ValueError(
                "`files` must not contain 'main.typ' (reserved for template)."
            )
        for key, value in files.items():
            if isinstance(value, str):
                raise TypeError(
                    f"`files[{key!r}]` must be `bytes`, got `str` "
                    "(`str` values are interpreted as filesystem paths by typst)."
                )

    source = template.encode() if isinstance(template, str) else template
    vfs: dict[str, bytes] = {"main.typ": source}
    if files is not None:
        vfs.update(files)

    sys_inputs = {"data": json.dumps(data, default=json_default)}

    with tempfile.TemporaryDirectory(prefix="typst-") as sandbox:
        if validate_only:
            output = f"{sandbox}/out.pdf"
        try:
            return typst.compile(  # type: ignore[no-any-return, call-overload]
                vfs,
                output=str(output) if output is not None else None,
                root=sandbox,
                ignore_system_fonts=True,
                font_paths=[str(p) for p in font_paths] if font_paths else [],
                sys_inputs=sys_inputs,
            )
        except typst.TypstError as exc:

            def sanitize(s: str) -> str:
                return s.replace(sandbox, "")

            raise CompilationError(
                sanitize(exc.message),
                diagnostic=sanitize(exc.diagnostic),
                hints=[sanitize(h) for h in exc.hints],
            ) from exc
