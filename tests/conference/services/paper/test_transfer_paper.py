import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import Conference, Paper, Track
from app.conference.services import PaperService
from app.core.models import User
from tests.helpers import update_object


@pytest.mark.django_db
class TestPaperServiceTransferPaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

    @pytest.fixture
    def new_owner(self, faker: Faker) -> User:
        return User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

    def test_happy_path(self, paper: Paper, new_owner: User) -> None:
        transferred = PaperService.transfer_paper(paper=paper, new_owner=new_owner)

        db_transferred = Paper.objects.get(pk=transferred.pk)
        assert db_transferred.owner_id == transferred.owner_id == new_owner.pk

    def test_raises_when_paper_deleted(self, paper: Paper, new_owner: User) -> None:
        update_object(paper, delete_time=timezone.now())

        with pytest.raises(Paper.DoesNotExist):
            PaperService.transfer_paper(paper=paper, new_owner=new_owner)

    def test_raises_when_conference_inactive(
        self,
        conference: Conference,
        paper: Paper,
        new_owner: User,
    ) -> None:
        update_object(conference, active=False)

        with pytest.raises(Paper.DoesNotExist):
            PaperService.transfer_paper(paper=paper, new_owner=new_owner)
