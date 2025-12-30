import pytest

from app.conference.models import Conference, Paper, PaperState, Track
from app.core.models import User


@pytest.fixture
def paper(user: User, conference: Conference, track: Track) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=PaperState.SUBMITTED,
    )
