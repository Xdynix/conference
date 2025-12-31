import pytest
from django.utils import timezone

from app.conference.models import Conference, Paper, PaperFinal, Track
from app.conference.services import PaperService
from app.conference.services.paper import PaperWithdrawnError
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPaperServiceSetFinalRevisionLimit:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
            final_revision_limit=1,
        )

    def test_happy_path(self, paper: Paper) -> None:
        result = PaperService.set_final_revision_limit(paper, count=5)

        db_paper = Paper.objects.get(pk=paper.pk)
        assert result.final_revision_limit == db_paper.final_revision_limit == 5

    def test_sets_limit_when_count_greater_than_current_finals(
        self,
        paper: Paper,
    ) -> None:
        PaperFinal.objects.create(paper=paper, revision=1, source_file="final1.zip")

        result = PaperService.set_final_revision_limit(paper, count=5)

        assert result.final_revision_limit == 5

    def test_uses_current_final_count_when_count_below_existing(
        self,
        paper: Paper,
    ) -> None:
        PaperFinal.objects.create(paper=paper, revision=1, source_file="final1.zip")
        PaperFinal.objects.create(paper=paper, revision=2, source_file="final2.zip")
        PaperFinal.objects.create(paper=paper, revision=3, source_file="final3.zip")

        result = PaperService.set_final_revision_limit(paper, count=1)

        assert result.final_revision_limit == 3

    def test_drains_quota_when_count_equals_current_finals(
        self,
        paper: Paper,
    ) -> None:
        PaperFinal.objects.create(paper=paper, revision=1, source_file="final1.zip")
        PaperFinal.objects.create(paper=paper, revision=2, source_file="final2.zip")

        result = PaperService.set_final_revision_limit(paper, count=2)

        assert result.final_revision_limit == 2

    def test_allows_setting_to_zero_when_no_finals_exist(
        self,
        paper: Paper,
    ) -> None:
        result = PaperService.set_final_revision_limit(paper, count=0)

        assert result.final_revision_limit == 0

    def test_raises_when_paper_withdrawn(self, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(
            PaperWithdrawnError,
            match="Cannot modify final revision limit for withdrawn papers",
        ):
            PaperService.set_final_revision_limit(paper, count=5)

    def test_raises_when_paper_deleted(self, paper: Paper) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Paper.DoesNotExist):
            PaperService.set_final_revision_limit(paper, count=5)
