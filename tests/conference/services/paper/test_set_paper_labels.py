import pytest

from app.conference.models import Conference, Paper, PaperLabel, Track
from app.conference.services import PaperService
from app.core.models import User


@pytest.mark.django_db
class TestPaperServiceSetPaperLabels:
    @pytest.fixture
    def paper(self, conference: Conference, track: Track, user: User) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Original Title",
        )

    def test_replaces_labels(self, paper: Paper) -> None:
        PaperLabel.objects.create(paper=paper, key="env", value="prod")
        PaperLabel.objects.create(paper=paper, key="tier", value="frontend")

        PaperService.set_paper_labels(paper, env="staging", owner="review")

        labels = {(label.key, label.value) for label in paper.labels.all()}
        assert labels == {("env", "staging"), ("owner", "review")}

    def test_empty_labels_clears_existing(self, paper: Paper) -> None:
        PaperLabel.objects.create(paper=paper, key="env", value="prod")
        PaperLabel.objects.create(paper=paper, key="tier", value="frontend")

        PaperService.set_paper_labels(paper)

        assert not paper.labels.exists()
