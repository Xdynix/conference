from unittest.mock import MagicMock

import pytest
from faker import Faker
from pydantic import ValidationError
from pytest_mock import MockerFixture

from app.verikit.types import VerifiedEmail


class TestVerifiedEmail:
    @pytest.fixture
    def mock_verify_token(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "app.verikit.services.EmailVerificationService.verify_token"
        )

    def test_happy_path(self, faker: Faker, mock_verify_token: MagicMock) -> None:
        email = faker.email()
        token = faker.pystr()
        mock_verify_token.return_value = True

        result = VerifiedEmail(email=email, token=token)

        assert result.email == email
        assert result.token == token
        mock_verify_token.assert_called_once_with(email, token)

    def test_raises_validation_error_when_token_invalid(
        self,
        faker: Faker,
        mock_verify_token: MagicMock,
    ) -> None:
        email = faker.email()
        token = faker.pystr()
        mock_verify_token.return_value = False

        with pytest.raises(
            ValidationError,
            match="Invalid or expired verification token",
        ):
            VerifiedEmail(email=email, token=token)

        mock_verify_token.assert_called_once_with(email, token)
