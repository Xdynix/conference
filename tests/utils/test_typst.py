import tempfile
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from faker import Faker
from pydantic import HttpUrl
from ulid import ULID

from app.utils.typst import CompilationError, compile_template, typst_json_default

MINIMAL_TEMPLATE = b'#let data = json(bytes(sys.inputs.at("data")))\nHello'


class TestTypstJsonDefault:
    def test_naive_datetime(self) -> None:
        result = typst_json_default(datetime(2024, 3, 15, 10, 30, 45))
        assert result == {
            "year": 2024,
            "month": 3,
            "day": 15,
            "hour": 10,
            "minute": 30,
            "second": 45,
        }

    def test_timezone_aware_datetime_rejected(self) -> None:
        with pytest.raises(ValueError, match="Timezone-aware datetime"):
            typst_json_default(datetime(2024, 3, 15, tzinfo=UTC))

    def test_date(self) -> None:
        result = typst_json_default(date(2024, 3, 15))
        assert result == {"year": 2024, "month": 3, "day": 15}

    def test_naive_time(self) -> None:
        result = typst_json_default(time(10, 30, 45))
        assert result == {"hour": 10, "minute": 30, "second": 45}

    def test_timezone_aware_time_rejected(self) -> None:
        with pytest.raises(ValueError, match="Timezone-aware time"):
            typst_json_default(time(10, 30, 45, tzinfo=UTC))

    def test_decimal(self) -> None:
        assert typst_json_default(Decimal("3.14")) == "3.14"

    def test_ulid(self, faker: Faker) -> None:
        value = ULID.from_bytes(faker.binary(length=16))
        assert typst_json_default(value) == str(value)

    def test_uuid(self) -> None:
        value = uuid4()
        assert typst_json_default(value) == str(value)

    def test_http_url(self, faker: Faker) -> None:
        value = HttpUrl(faker.url())
        assert typst_json_default(value) == str(value)


class TestCompileTemplate:
    def test_happy_path(self) -> None:
        result = compile_template(MINIMAL_TEMPLATE, {})
        assert isinstance(result, bytes)
        assert result[:5] == b"%PDF-"

    def test_output_writes_to_file(self, tmp_path: Path) -> None:
        output = tmp_path / "out.pdf"
        result = compile_template(MINIMAL_TEMPLATE, {}, output=output)
        assert result is None
        assert output.read_bytes()[:5] == b"%PDF-"

    def test_validate_only(self) -> None:
        result = compile_template(MINIMAL_TEMPLATE, {}, validate_only=True)
        assert result is None

    def test_validate_only_with_output_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            compile_template(  # type:ignore[call-overload]
                MINIMAL_TEMPLATE,
                {},
                output=tmp_path / "out.pdf",
                validate_only=True,
            )

    def test_str_template(self) -> None:
        template = '#let data = json(bytes(sys.inputs.at("data")))\nHello'
        result = compile_template(template, {})
        assert result[:5] == b"%PDF-"

    def test_data_accessible_in_template(self) -> None:
        template = (
            b'#let data = json(bytes(sys.inputs.at("data")))\n'
            b"#data.greeting from #data.name"
        )
        result = compile_template(template, {"greeting": "Hello", "name": "World"})
        assert result[:5] == b"%PDF-"

    def test_datetime_display_in_template(self) -> None:
        template = (
            b'#let data = json(bytes(sys.inputs.at("data")))\n'
            b"#let d = datetime(..data.submitted_at)\n"
            b'Submitted on #d.display("[month repr:long] [day], [year]")'
        )
        data = {"submitted_at": datetime(2024, 3, 15, 10, 30, 0)}
        result = compile_template(template, data)
        assert result[:5] == b"%PDF-"

    def test_files_passed_to_virtual_fs(self) -> None:
        helper = b'#let greeting = "Hello"'
        template = b'#import "helper.typ": greeting\n#greeting World'
        result = compile_template(template, {}, files={"helper.typ": helper})
        assert result[:5] == b"%PDF-"

    def test_files_rejects_main_typ(self) -> None:
        with pytest.raises(ValueError, match=r"main.typ"):
            compile_template(b"Hello", {}, files={"main.typ": b"evil"})

    def test_files_rejects_str_value(self) -> None:
        with pytest.raises(TypeError, match=r"must be `bytes`, got `str`"):
            compile_template(
                b"Hello",
                {},
                files={"logo.png": "path/to/file"},  # type: ignore[dict-item]
            )

    def test_custom_json_default(self) -> None:
        class Custom:
            pass

        def custom_default(obj: Any) -> Any:
            if isinstance(obj, Custom):
                return "custom_value"
            return typst_json_default(obj)

        template = b'#let data = json(bytes(sys.inputs.at("data")))\n#data.field'
        result = compile_template(
            template,
            {"field": Custom()},
            json_default=custom_default,
        )
        assert result[:5] == b"%PDF-"


class TestCompileTemplateErrors:
    def test_syntax_error(self) -> None:
        with pytest.raises(CompilationError):
            compile_template(b"#let x = ", {})

    def test_undefined_variable(self) -> None:
        with pytest.raises(CompilationError):
            compile_template(b"#undefined_var", {})

    def test_missing_sys_input_key(self) -> None:
        with pytest.raises(CompilationError):
            compile_template(b'#sys.inputs.at("nonexistent")', {})

    def test_error_has_diagnostic(self) -> None:
        with pytest.raises(CompilationError) as exc_info:
            compile_template(b"#let x = ", {})
        assert exc_info.value.diagnostic != ""

    def test_error_sanitization(self) -> None:
        with pytest.raises(CompilationError) as exc_info:
            compile_template(b"#let x = ", {})
        err = exc_info.value
        for field in [str(err), err.diagnostic, *err.hints]:
            assert "typst-" not in field


class TestCompileTemplateSecurity:
    def test_dict_mode_blocks_absolute_read(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("sensitive data")
        # The file exists on disk; any failure is due to virtual FS isolation.
        template = f'#read("{secret}")'.encode()
        with pytest.raises(CompilationError):
            compile_template(template, {})

    def test_dict_mode_blocks_relative_traversal(self) -> None:
        # The typst sandbox is created via TemporaryDirectory() in the system temp dir,
        # so "../<name>" resolves to a sibling in that directory.
        secret = Path(tempfile.gettempdir()) / "typst_test_secret.txt"
        secret.write_text("sensitive data")
        try:
            template = f'#read("../{secret.name}")'.encode()
            with pytest.raises(CompilationError):
                compile_template(template, {})
        finally:
            secret.unlink()

    def test_package_import_blocked(self) -> None:
        # "abbr" v0.3.0 is a real package on packages.typst.org. Using a real package
        # proves the failure is due to isolation, not a typo.
        template = b'#import "@preview/abbr:0.3.0": abbr'
        with pytest.raises(CompilationError):
            compile_template(template, {})

    def test_plugin_blocked(self) -> None:
        # Minimal valid WASM module (magic + version). Including it in files proves the
        # file exists in the virtual FS; any failure is due to plugin loading being
        # rejected, not file absence.
        wasm = b"\x00asm\x01\x00\x00\x00"
        template = b'#plugin("exploit.wasm")'
        with pytest.raises(CompilationError):
            compile_template(template, {}, files={"exploit.wasm": wasm})
