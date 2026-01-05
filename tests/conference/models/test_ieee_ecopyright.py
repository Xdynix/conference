import pytest
from faker import Faker

from app.conference.models import (
    Conference,
    IEEEeCopyrightConfig,
    IEEEeCopyrightConsent,
    Paper,
    Track,
)
from app.core.models import User


class TestIEEEeCopyrightConfig:
    def test_str(self) -> None:
        conference = Conference(name="ICSE-2025")
        config = IEEEeCopyrightConfig(
            conference=conference,
            publication_title="Proceedings of ICSE 2025",
            article_source="ICSE25",
        )
        assert str(config) == "IEEE eCopyright config for ICSE-2025"


@pytest.mark.django_db
class TestIEEEeCopyrightConsent:
    @pytest.fixture
    def paper(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
    ) -> Paper:
        return Paper(
            conference=conference,
            track=track,
            code=faker.lexify(text="????-###"),
            owner=user,
            title=faker.sentence(),
        )

    def test_str(self, paper: Paper) -> None:
        consent = IEEEeCopyrightConsent(paper=paper)
        assert str(consent) == f"IEEE eCopyright consent for {paper}"
