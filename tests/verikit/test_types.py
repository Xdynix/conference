from unittest.mock import MagicMock

import pytest
from faker import Faker
from pydantic import TypeAdapter, ValidationError
from pytest_mock import MockerFixture

from app.verikit.types import VerifiedEmailStr


class TestVerifiedEmailStr:
    @pytest.fixture
    def mock_verify_token(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "app.verikit.services.EmailVerificationService.verify_token"
        )

    def test_happy_path(self, faker: Faker, mock_verify_token: MagicMock) -> None:
        email = faker.email()
        token = faker.pystr()
        mock_verify_token.return_value = email

        result = TypeAdapter(VerifiedEmailStr).validate_python(token)

        assert result == email
        mock_verify_token.assert_called_once_with(token)

    def test_normalize_email(self, faker: Faker, mock_verify_token: MagicMock) -> None:
        email = faker.email()
        upper_email = email.upper()
        token = faker.pystr()
        mock_verify_token.return_value = upper_email

        result = TypeAdapter(VerifiedEmailStr).validate_python(token)

        assert result == email
        mock_verify_token.assert_called_once_with(token)

    def test_raises_validation_error_when_token_invalid(
        self,
        faker: Faker,
        mock_verify_token: MagicMock,
    ) -> None:
        token = faker.pystr()
        mock_verify_token.return_value = None

        with pytest.raises(
            ValidationError,
            match="Invalid or expired verification token",
        ):
            TypeAdapter(VerifiedEmailStr).validate_python(token)

        mock_verify_token.assert_called_once_with(token)

    def test_raises_validation_error_when_subject_invalid(
        self,
        faker: Faker,
        mock_verify_token: MagicMock,
    ) -> None:
        token = faker.pystr()
        mock_verify_token.return_value = "invalid-value"

        with pytest.raises(
            ValidationError,
            match=" value is not a valid email address",
        ):
            TypeAdapter(VerifiedEmailStr).validate_python(token)
