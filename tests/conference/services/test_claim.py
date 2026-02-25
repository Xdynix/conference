import pytest
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import Conference, Paper, PaperAuthor, PaperClaim, Track
from app.conference.services import ClaimService
from app.conference.services.claim import ClaimConflictError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestClaimServiceDeriveClaimEmail:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

    def test_returns_lowercase_email(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Alice",
            family_name="Smith",
            email="Alice@Example.COM",
            corresponding=True,
        )

        result = ClaimService.derive_claim_email(paper)

        assert result == "alice@example.com"

    def test_raises_when_no_corresponding_authors(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Alice",
            family_name="Smith",
            email="alice@example.com",
            corresponding=False,
        )

        with pytest.raises(ValueError, match="exactly one corresponding author"):
            ClaimService.derive_claim_email(paper)

    def test_raises_when_multiple_corresponding_authors(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Alice",
            family_name="Smith",
            email="alice@example.com",
            corresponding=True,
        )
        PaperAuthor.objects.create(
            paper=paper,
            ordering=1,
            given_name="Bob",
            family_name="Jones",
            email="bob@example.com",
            corresponding=True,
        )

        with pytest.raises(ValueError, match="exactly one corresponding author"):
            ClaimService.derive_claim_email(paper)

    def test_raises_when_no_authors_exist(self, paper: Paper) -> None:
        with pytest.raises(ValueError, match="exactly one corresponding author"):
            ClaimService.derive_claim_email(paper)

    def test_raises_when_corresponding_author_has_no_email(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Alice",
            family_name="Smith",
            email="",
            corresponding=True,
        )

        with pytest.raises(ValueError, match="must have an email address"):
            ClaimService.derive_claim_email(paper)


@pytest.mark.django_db
class TestClaimServiceSetClaim:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        paper = Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Alice",
            family_name="Smith",
            email="alice@example.com",
            corresponding=True,
        )
        return paper

    def test_creates_claim_when_no_user_exists(self, paper: Paper) -> None:
        claim = ClaimService.set_claim(paper)

        assert claim is not None
        assert claim.email == "alice@example.com"
        assert claim.paper_id == paper.pk
        assert PaperClaim.objects.filter(paper=paper).exists()

    def test_transfers_when_user_exists(self, paper: Paper, faker: Faker) -> None:
        target_user = User.objects.create_user(
            username=faker.user_name(),
            email="alice@example.com",
        )

        result = ClaimService.set_claim(paper)

        assert result is None
        paper.refresh_from_db()
        assert paper.owner_id == target_user.pk
        assert not PaperClaim.objects.filter(paper=paper).exists()

    def test_updates_claim_when_email_changed(self, paper: Paper) -> None:
        PaperClaim.objects.create(paper=paper, email="old@example.com")

        claim = ClaimService.set_claim(paper)

        assert claim is not None
        assert claim.email == "alice@example.com"
        assert PaperClaim.objects.filter(paper=paper).count() == 1

    def test_idempotent_when_email_unchanged(self, paper: Paper) -> None:
        existing = PaperClaim.objects.create(paper=paper, email="alice@example.com")

        claim = ClaimService.set_claim(paper)

        assert claim is not None
        assert claim.pk == existing.pk
        assert claim.email == "alice@example.com"

    def test_raises_when_paper_deleted(self, paper: Paper) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Paper.DoesNotExist):
            ClaimService.set_claim(paper)

    def test_raises_when_email_changed_concurrently(
        self,
        paper: Paper,
        mocker: MockerFixture,
    ) -> None:
        original = ClaimService.derive_claim_email
        mocker.patch.object(
            ClaimService,
            "derive_claim_email",
            side_effect=[original(paper), "changed@example.com"],
        )

        with pytest.raises(ClaimConflictError, match="modified concurrently"):
            ClaimService.set_claim(paper)

        assert not PaperClaim.objects.filter(paper=paper).exists()

    def test_case_insensitive_user_lookup(self, paper: Paper, faker: Faker) -> None:
        target_user = User.objects.create_user(
            username=faker.user_name(),
            email="ALICE@EXAMPLE.COM",
        )

        result = ClaimService.set_claim(paper)

        assert result is None
        paper.refresh_from_db()
        assert paper.owner_id == target_user.pk


@pytest.mark.django_db
class TestClaimServiceRemoveClaim:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

    def test_deletes_existing_claim(self, paper: Paper) -> None:
        PaperClaim.objects.create(paper=paper, email="alice@example.com")

        ClaimService.remove_claim(paper)

        assert not PaperClaim.objects.filter(paper=paper).exists()

    def test_noop_when_no_claim_exists(self, paper: Paper) -> None:
        ClaimService.remove_claim(paper)

        assert not PaperClaim.objects.filter(paper=paper).exists()


@pytest.mark.django_db
class TestClaimServiceFulfillClaims:
    @pytest.fixture
    def paper_a(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-A",
            title="Paper A",
        )

    @pytest.fixture
    def paper_b(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-B",
            title="Paper B",
        )

    def test_transfers_matching_papers(
        self,
        paper_a: Paper,
        paper_b: Paper,
        faker: Faker,
    ) -> None:
        new_user = User.objects.create_user(
            username=faker.user_name(),
            email="claimer@example.com",
        )
        PaperClaim.objects.create(paper=paper_a, email="claimer@example.com")
        PaperClaim.objects.create(paper=paper_b, email="claimer@example.com")

        result = ClaimService.fulfill_claims(new_user)

        assert set(result) == {"PAPER-A", "PAPER-B"}
        paper_a.refresh_from_db()
        paper_b.refresh_from_db()
        assert paper_a.owner_id == new_user.pk
        assert paper_b.owner_id == new_user.pk
        assert not PaperClaim.objects.filter(paper__in=[paper_a, paper_b]).exists()

    def test_returns_empty_list_when_no_claims_match(self, faker: Faker) -> None:
        new_user = User.objects.create_user(
            username=faker.user_name(),
            email="nobody@example.com",
        )

        result = ClaimService.fulfill_claims(new_user)

        assert result == []

    def test_skips_deleted_papers(
        self,
        paper_a: Paper,
        paper_b: Paper,
        faker: Faker,
    ) -> None:
        new_user = User.objects.create_user(
            username=faker.user_name(),
            email="claimer@example.com",
        )
        PaperClaim.objects.create(paper=paper_a, email="claimer@example.com")
        PaperClaim.objects.create(paper=paper_b, email="claimer@example.com")
        update_object(paper_a, delete_time=timezone.now())

        result = ClaimService.fulfill_claims(new_user)

        assert result == ["PAPER-B"]
        paper_b.refresh_from_db()
        assert paper_b.owner_id == new_user.pk

    def test_returns_empty_list_when_all_papers_deleted(
        self,
        paper_a: Paper,
        faker: Faker,
    ) -> None:
        new_user = User.objects.create_user(
            username=faker.user_name(),
            email="claimer@example.com",
        )
        PaperClaim.objects.create(paper=paper_a, email="claimer@example.com")
        update_object(paper_a, delete_time=timezone.now())

        result = ClaimService.fulfill_claims(new_user)

        assert result == []

    def test_case_insensitive_email_matching(
        self,
        paper_a: Paper,
        faker: Faker,
    ) -> None:
        new_user = User.objects.create_user(
            username=faker.user_name(),
            email="Claimer@Example.COM",
        )
        PaperClaim.objects.create(paper=paper_a, email="claimer@example.com")

        result = ClaimService.fulfill_claims(new_user)

        assert result == ["PAPER-A"]
        paper_a.refresh_from_db()
        assert paper_a.owner_id == new_user.pk
