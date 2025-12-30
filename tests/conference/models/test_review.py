import pytest
from django.db import IntegrityError
from faker import Faker

from app.conference.models import Conference, Paper, Review, Track
from app.conference.models.review import MAX_SCORE, MIN_SCORE, AdminComment, ReviewState
from app.core.models import User


@pytest.fixture
def paper(faker: Faker, user: User, conference: Conference, track: Track) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        code=faker.lexify(text="????-###"),
        owner=user,
        title=faker.sentence(),
    )


@pytest.mark.django_db(transaction=True)
class TestReview:
    def test_str_with_reviewer(self, user: User, paper: Paper) -> None:
        review = Review(paper=paper, reviewer=user)
        assert str(review) == f"{paper} - {user}"

    def test_str_with_offline_reviewer_name(self, paper: Paper) -> None:
        review = Review(paper=paper, offline_reviewer_name="Dr. Offline")
        assert str(review) == f"{paper} - Dr. Offline"

    def test_str_without_reviewer(self, paper: Paper) -> None:
        review = Review(paper=paper)
        assert str(review) == f"{paper} - (Unassigned)"

    def test_unique_active_review(self, user: User, paper: Paper) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.PENDING,
        )

        with pytest.raises(IntegrityError):
            Review.objects.create(
                paper=paper,
                reviewer=user,
                state=ReviewState.ACCEPTED,
            )

    def test_unique_active_allows_declined(self, user: User, paper: Paper) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.DECLINED,
        )

        Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.PENDING,
        )

    def test_unique_active_allows_offline_reviews(self, paper: Paper) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=None,
            state=ReviewState.PENDING,
        )
        Review.objects.create(
            paper=paper,
            reviewer=None,
            state=ReviewState.PENDING,
        )

    def test_unique_offline_review(self, paper: Paper) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="Dr. External",
            state=ReviewState.SUBMITTED,
        )

        with pytest.raises(IntegrityError):
            Review.objects.create(
                paper=paper,
                reviewer=None,
                offline_reviewer_name="Dr. External",
                state=ReviewState.SUBMITTED,
            )

    def test_unique_offline_allows_different_papers(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
        paper: Paper,
    ) -> None:
        other_paper = Paper.objects.create(
            conference=conference,
            track=track,
            code=faker.lexify(text="????-###"),
            owner=user,
            title=faker.sentence(),
        )
        Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="Dr. External",
            state=ReviewState.SUBMITTED,
        )

        Review.objects.create(
            paper=other_paper,
            reviewer=None,
            offline_reviewer_name="Dr. External",
            state=ReviewState.SUBMITTED,
        )

    def test_unique_offline_allows_empty_name(self, paper: Paper) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="",
            state=ReviewState.SUBMITTED,
        )

        Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="",
            state=ReviewState.SUBMITTED,
        )

    def test_unique_offline_only_applies_to_offline_reviews(
        self,
        user: User,
        paper: Paper,
    ) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=user,
            offline_reviewer_name="Dr. External",
            state=ReviewState.SUBMITTED,
        )

        Review.objects.create(
            paper=paper,
            reviewer=None,
            offline_reviewer_name="Dr. External",
            state=ReviewState.SUBMITTED,
        )

    @pytest.mark.parametrize(
        "field_name",
        [
            "originality",
            "significance",
            "technical",
            "reference",
            "presentation",
            "match_topic",
            "recommendation",
        ],
    )
    def test_score_range_enforced(self, paper: Paper, field_name: str) -> None:
        with pytest.raises(IntegrityError):
            Review.objects.create(
                paper=paper,
                reviewer=None,
                **{field_name: MIN_SCORE - 1},
            )

        with pytest.raises(IntegrityError):
            Review.objects.create(
                paper=paper,
                reviewer=None,
                **{field_name: MAX_SCORE + 1},
            )


@pytest.mark.django_db
class TestAdminComment:
    def test_str_with_author(self, paper: Paper, user: User) -> None:
        comment = AdminComment(paper=paper, author=user, content="Looks good.")
        assert str(comment) == f"{paper} - {user}"

    def test_str_without_author(self, paper: Paper) -> None:
        comment = AdminComment(paper=paper, content="Looks good.")
        assert str(comment) == f"{paper} - (Unknown)"
