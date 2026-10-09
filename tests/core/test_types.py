import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.types import EmailStr


class TestEmailStr:
    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            ("John@Example.com", "john@example.com"),
            pytest.param("john@exämple.com", "john@exämple.com", id="idn_domain"),
            ("John Doe <john@example.com>", "john@example.com"),
        ],
    )
    def test_happy_path(self, email: str, expected: str) -> None:
        assert TypeAdapter(EmailStr).validate_python(email) == expected

    @pytest.mark.parametrize(
        "email",
        [
            pytest.param("jöhn@example.com", id="non_ascii_local_part"),
            pytest.param("Jöhn <jöhn@example.com>", id="non_ascii_local_part_named"),
        ],
    )
    def test_rejects_non_ascii_local_part(self, email: str) -> None:
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            TypeAdapter(EmailStr).validate_python(email)
