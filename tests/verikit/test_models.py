import pytest
from django.utils import timezone
from faker import Faker

from app.verikit.models import EmailVerification


@pytest.mark.django_db
class TestEmailVerification:
    def test_str_pending_verification(self, faker: Faker) -> None:
        email = faker.email()
        verification = EmailVerification.objects.create(
            email=email,
            code_hash="test_hash",
            expire_time=timezone.now(),
        )
        assert str(verification) == f"{email} (pending)"

    def test_str_completed_verification(self, faker: Faker) -> None:
        email = faker.email()
        verification = EmailVerification.objects.create(
            email=email,
            code_hash="test_hash",
            expire_time=timezone.now(),
            verify_time=timezone.now(),
        )
        assert str(verification) == f"{email} (verified)"
