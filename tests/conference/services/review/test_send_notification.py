from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.mail import EmailMessage
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    Conference,
    Paper,
    Profile,
    Review,
    ReviewerNotificationLog,
    ReviewState,
)
from app.conference.services.review import (
    ReviewerNotificationContext,
    ReviewerNotificationService,
    SendNotificationStatus,
)
from app.core.models import User
from app.utils.email import EmailTemplate
from tests.helpers import approx_now


@pytest.fixture
def template() -> EmailTemplate:
    return EmailTemplate(
        subject="Notification for {{ conference_name }}",
        body="Hello {{ given_name }}, you have {{ pending_review_count }} pending.",
    )


@pytest.fixture
def mock_send(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(EmailMessage, "send")


@pytest.fixture
def reviewer(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name(), email=faker.email())
    Profile.objects.create(
        user=user,
        given_name=faker.first_name(),
        family_name=faker.last_name(),
        affiliation=faker.company(),
    )
    return user


class TestReviewerNotificationContextSample:
    def test_happy_path(self, settings: LazySettings) -> None:
        site_name = "Test Site"
        settings.SITE_NAME = site_name

        context = ReviewerNotificationContext.sample()

        assert context.site_name == site_name
        assert context.conference_name == "CONF-2025"
        assert context.conference_display_name == "Sample Conference 2025"
        assert context.given_name == "John"
        assert context.family_name == "Doe"
        assert context.affiliation == "Sample University"
        assert context.pending_review_count == 3
        assert context.accepted_review_count == 1

    def test_context_can_be_used_for_template_rendering(
        self,
        template: EmailTemplate,
    ) -> None:
        context = ReviewerNotificationContext.sample()

        rendered = template.render(context)

        assert "CONF-2025" in rendered.subject
        assert "John" in rendered.body
        assert "3 pending" in rendered.body


@pytest.mark.django_db(transaction=True)
class TestReviewerNotificationServiceSendNotification:
    @pytest.mark.parametrize("state", [ReviewState.PENDING, ReviewState.ACCEPTED])
    def test_happy_path(
        self,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,
        state: ReviewState,
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=state)

        sent, reviewer_email = ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
        )

        assert sent is True
        assert reviewer_email == reviewer.email

        mock_send.assert_called_once()

    def test_skips_when_no_actionable_reviews(
        self,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        Review.objects.create(
            paper=paper,
            reviewer=reviewer,
            state=ReviewState.DECLINED,
        )

        sent, reviewer_email = ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
        )

        assert sent is False
        assert reviewer_email == reviewer.email

        mock_send.assert_not_called()

    def test_skips_recently_notified(
        self,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=ReviewState.PENDING)
        ReviewerNotificationLog.objects.create(
            conference=conference,
            reviewer=reviewer,
            last_notification_time=timezone.now(),
        )

        sent, reviewer_email = ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
        )

        assert sent is False
        assert reviewer_email == reviewer.email

        mock_send.assert_not_called()

    def test_force_send_to_recent(
        self,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=ReviewState.PENDING)
        ReviewerNotificationLog.objects.create(
            conference=conference,
            reviewer=reviewer,
            last_notification_time=timezone.now(),
        )

        sent, _ = ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
            force_send_to_recent=True,
        )

        assert sent is True

        mock_send.assert_called_once()

    def test_sends_after_interval_expires(
        self,
        settings: LazySettings,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=ReviewState.PENDING)
        ReviewerNotificationLog.objects.create(
            conference=conference,
            reviewer=reviewer,
            last_notification_time=(
                timezone.now()
                - settings.REVIEWER_NOTIFICATION_EMAIL_INTERVAL
                - timedelta(seconds=1)
            ),
        )

        sent, _ = ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
        )

        assert sent is True

        mock_send.assert_called_once()

    def test_creates_notification_log(
        self,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=ReviewState.PENDING)
        assert not ReviewerNotificationLog.objects.filter(
            conference=conference,
            reviewer=reviewer,
        ).exists()

        ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
        )

        log = ReviewerNotificationLog.objects.get(
            conference=conference,
            reviewer=reviewer,
        )
        assert log.last_notification_time == approx_now()

    def test_updates_existing_notification_log(
        self,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,  # noqa: ARG002
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=ReviewState.PENDING)

        ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
        )
        ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
            force_send_to_recent=True,
        )

        assert (
            ReviewerNotificationLog.objects.filter(
                conference=conference,
                reviewer=reviewer,
            ).count()
            == 1
        )

        log = ReviewerNotificationLog.objects.get(
            conference=conference,
            reviewer=reviewer,
        )
        assert log.last_notification_time == approx_now()

    def test_raises_for_nonexistent_reviewer(
        self,
        conference: Conference,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        with pytest.raises(User.DoesNotExist):
            ReviewerNotificationService.send_notification(
                conference,
                ULID(),
                template=template,
            )

        mock_send.assert_not_called()

    def test_passes_reply_to_to_email(
        self,
        mocker: MockerFixture,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=ReviewState.PENDING)
        mock_build = mocker.patch(
            "app.utils.email.RenderedEmail.build_message",
            return_value=MagicMock(),
        )

        ReviewerNotificationService.send_notification(
            conference,
            reviewer.uid,
            template=template,
            reply_to="chair@example.com",
        )

        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["reply_to"] == "chair@example.com"

    def test_uses_database_transaction(
        self,
        mocker: MockerFixture,
        conference: Conference,
        reviewer: User,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        Review.objects.create(paper=paper, reviewer=reviewer, state=ReviewState.PENDING)
        mocker.patch.object(
            ReviewerNotificationLog,
            "save",
            side_effect=RuntimeError("Test Error"),
        )

        with pytest.raises(RuntimeError, match="Test Error"):
            ReviewerNotificationService.send_notification(
                conference,
                reviewer.uid,
                template=template,
            )

        assert not ReviewerNotificationLog.objects.filter(
            conference=conference,
            reviewer=reviewer,
        ).exists()

        mock_send.assert_not_called()

    def test_sends_without_profile(
        self,
        faker: Faker,
        conference: Conference,
        paper: Paper,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        reviewer_no_profile = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        Review.objects.create(
            paper=paper,
            reviewer=reviewer_no_profile,
            state=ReviewState.PENDING,
        )

        sent, _ = ReviewerNotificationService.send_notification(
            conference,
            reviewer_no_profile.uid,
            template=template,
        )

        assert sent is True

        mock_send.assert_called_once()


@pytest.mark.django_db(transaction=True)
class TestReviewerNotificationServiceSendNotifications:
    @pytest.fixture
    def reviewer_a(self, faker: Faker, paper: Paper) -> User:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        Profile.objects.create(user=user, given_name="Alice")
        Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.PENDING,
        )
        return user

    @pytest.fixture
    def reviewer_b(self, faker: Faker, paper: Paper) -> User:
        user = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )
        Profile.objects.create(user=user, given_name="Bob")
        Review.objects.create(
            paper=paper,
            reviewer=user,
            state=ReviewState.PENDING,
        )
        return user

    def test_happy_path(
        self,
        conference: Conference,
        template: EmailTemplate,
        mock_send: MagicMock,
        reviewer_a: User,
        reviewer_b: User,
    ) -> None:
        results = ReviewerNotificationService.send_notifications(
            conference,
            [reviewer_a.uid, reviewer_b.uid],
            template=template,
        )

        [result_a, result_b] = results
        assert result_a.reviewer == reviewer_a.uid
        assert result_a.status == SendNotificationStatus.SENT
        assert result_a.reviewer_email == reviewer_a.email
        assert result_b.reviewer == reviewer_b.uid
        assert result_b.status == SendNotificationStatus.SENT
        assert result_b.reviewer_email == reviewer_b.email

        assert mock_send.call_count == 2

    def test_empty_list(
        self,
        conference: Conference,
        template: EmailTemplate,
        mock_send: MagicMock,
    ) -> None:
        results = ReviewerNotificationService.send_notifications(
            conference,
            [],
            template=template,
        )

        assert results == []

        mock_send.assert_not_called()

    def test_not_found_reviewer(
        self,
        conference: Conference,
        template: EmailTemplate,
        mock_send: MagicMock,
        reviewer_a: User,
    ) -> None:
        nonexistent_uid = ULID()

        results = ReviewerNotificationService.send_notifications(
            conference,
            [reviewer_a.uid, nonexistent_uid],
            template=template,
        )

        [result_a, result_nonexistent] = results
        assert result_a.reviewer == reviewer_a.uid
        assert result_a.status == SendNotificationStatus.SENT
        assert result_nonexistent.reviewer == nonexistent_uid
        assert result_nonexistent.status == SendNotificationStatus.NOT_FOUND
        assert result_nonexistent.reason is not None

        mock_send.assert_called_once()

    def test_skipped_reviewer(
        self,
        faker: Faker,
        conference: Conference,
        template: EmailTemplate,
        mock_send: MagicMock,
        reviewer_a: User,
    ) -> None:
        reviewer_no_reviews = User.objects.create_user(
            username=faker.user_name(),
            email=faker.email(),
        )

        results = ReviewerNotificationService.send_notifications(
            conference,
            [reviewer_a.uid, reviewer_no_reviews.uid],
            template=template,
        )

        [result_a, result_b] = results
        assert result_a.reviewer == reviewer_a.uid
        assert result_a.status == SendNotificationStatus.SENT
        assert result_b.reviewer == reviewer_no_reviews.uid
        assert result_b.status == SendNotificationStatus.SKIPPED
        assert result_b.reviewer_email == reviewer_no_reviews.email
        assert result_b.reason is not None

        mock_send.assert_called_once()

    def test_failure_does_not_affect_others(
        self,
        conference: Conference,
        template: EmailTemplate,
        mock_send: MagicMock,
        reviewer_a: User,
        reviewer_b: User,
    ) -> None:
        mock_send.side_effect = [
            None,
            RuntimeError("Email server error"),
        ]

        results = ReviewerNotificationService.send_notifications(
            conference,
            [reviewer_a.uid, reviewer_b.uid],
            template=template,
        )

        [result_a, result_b] = results
        assert result_a.reviewer == reviewer_a.uid
        assert result_a.status == SendNotificationStatus.SENT
        assert result_b.reviewer == reviewer_b.uid
        assert result_b.status == SendNotificationStatus.FAILED
        assert result_b.reason is not None

        assert mock_send.call_count == 2

    def test_force_send_to_recent(
        self,
        conference: Conference,
        template: EmailTemplate,
        mock_send: MagicMock,
        reviewer_a: User,
    ) -> None:
        ReviewerNotificationLog.objects.create(
            conference=conference,
            reviewer=reviewer_a,
            last_notification_time=timezone.now(),
        )

        results = ReviewerNotificationService.send_notifications(
            conference,
            [reviewer_a.uid],
            template=template,
            force_send_to_recent=True,
        )

        [result] = results
        assert result.reviewer == reviewer_a.uid
        assert result.status == SendNotificationStatus.SENT

        mock_send.assert_called_once()
