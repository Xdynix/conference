from datetime import timedelta
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from ulid import ULID

from app.conference.models import (
    Conference,
    ConferenceVisibility,
    DuplicateMatchType,
    Paper,
    PaperState,
    Profile,
    Track,
    TrackRole,
    TrackRoleAssignment,
    TrackVisibility,
)
from app.conference.models.duplicate import (
    DuplicateAcknowledgment,
    DuplicateMatch,
    DuplicateReport,
    DuplicateReportState,
)
from app.core.models import User
from tests.helpers import ApproxDatetime, any_str, approx_now, update_object


def make_paper(
    conference: Conference,
    track: Track,
    owner: User,
    code: str,
    title: str = "Paper",
) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=owner,
        code=code,
        title=title,
    )


def canonical_pair(paper_a: Paper, paper_b: Paper) -> dict[str, Paper]:
    if paper_a.pk > paper_b.pk:
        paper_a, paper_b = paper_b, paper_a
    return {"paper_a": paper_a, "paper_b": paper_b}


def make_match(
    report: DuplicateReport,
    paper_a: Paper,
    paper_b: Paper,
    match_type: str = DuplicateMatchType.FILE_HASH,
    score: float = 1.0,
) -> DuplicateMatch:
    return DuplicateMatch.objects.create(
        report=report,
        **canonical_pair(paper_a, paper_b),
        match_type=match_type,
        score=score,
    )


@pytest.fixture
def report() -> DuplicateReport:
    return DuplicateReport.objects.create(state=DuplicateReportState.SUCCESS)


@pytest.fixture
def other_conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
        visibility=ConferenceVisibility.PUBLIC,
    )


@pytest.fixture
def other_track(faker: Faker, other_conference: Conference) -> Track:
    return Track.objects.create(
        conference=other_conference,
        display_name=faker.word(),
        visibility=TrackVisibility.PUBLIC,
    )


@pytest.fixture
def hidden_conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
        visibility=ConferenceVisibility.MEMBER_ONLY,
    )


@pytest.fixture
def hidden_track(faker: Faker, hidden_conference: Conference) -> Track:
    return Track.objects.create(
        conference=hidden_conference,
        display_name=faker.word(),
    )


@pytest.mark.django_db
class TestGetDuplicateReport:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:get-duplicate-report", args=[conference_name])

    def test_returns_latest_successful_report(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        DuplicateReport.objects.create(
            state=DuplicateReportState.SUCCESS,
            create_time=timezone.now() - timedelta(hours=1),
        )
        new_report = DuplicateReport.objects.create(state=DuplicateReportState.SUCCESS)
        # A failed report created after both should be ignored.
        DuplicateReport.objects.create(state=DuplicateReportState.FAILED)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["create_time"] == ApproxDatetime(new_report.create_time)

    def test_empty_matches_for_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        report: DuplicateReport,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json()["matches"] == []

    def test_single_match_both_papers_in_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001", "Alpha")
        paper_b = make_paper(conference, track, conference_chair, "P-002", "Beta")
        make_match(report, paper_a, paper_b)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [match] = data["matches"]
        assert match["match_type"] == DuplicateMatchType.FILE_HASH
        assert match["score"] == 1.0
        assert "acknowledgment" not in match

        pair_a, pair_b = match["pair"]
        assert pair_a["visibility"] == "visible"
        assert pair_a["conference"] == conference.name
        assert pair_a["uid"] == str(paper_a.uid)
        assert pair_a["title"] == "Alpha"
        assert pair_a["track"] == {
            "uid": str(track.uid),
            "display_name": track.display_name,
        }
        assert pair_b["visibility"] == "visible"
        assert pair_b["uid"] == str(paper_b.uid)

    def test_only_matches_involving_conference_returned(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        other_conference: Conference,
        other_track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        paper_other_1 = make_paper(
            other_conference,
            other_track,
            conference_chair,
            "O-001",
        )
        paper_other_2 = make_paper(
            other_conference,
            other_track,
            conference_chair,
            "O-002",
        )
        make_match(report, paper_own, paper_other_1)
        make_match(report, paper_other_1, paper_other_2)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert len(response.json()["matches"]) == 1

    def test_match_included_when_only_paper_a_in_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        other_conference: Conference,
        other_track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        paper_other = make_paper(
            other_conference,
            other_track,
            conference_chair,
            "O-001",
        )
        make_match(report, paper_own, paper_other)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert len(response.json()["matches"]) == 1

    def test_match_included_when_only_paper_b_in_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        other_conference: Conference,
        other_track: Track,
        report: DuplicateReport,
    ) -> None:
        # Create other paper first so it gets the smaller PK (becomes paper_a).
        paper_other = make_paper(
            other_conference,
            other_track,
            conference_chair,
            "O-001",
        )
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        make_match(report, paper_other, paper_own)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert len(response.json()["matches"]) == 1

    def test_paper_visible_when_admin_of_its_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001", "Alpha")
        paper_b = make_paper(conference, track, conference_chair, "P-002", "Beta")
        make_match(report, paper_a, paper_b)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        pair_a = response.json()["matches"][0]["pair"][0]
        assert pair_a["visibility"] == "visible"
        assert pair_a["conference"] == conference.name
        assert pair_a["uid"] == str(paper_a.uid)
        assert pair_a["code"] == "P-001"
        assert pair_a["title"] == "Alpha"
        assert pair_a["state"] == PaperState.DRAFT
        assert pair_a["create_time"] == any_str
        assert pair_a["track"] == {
            "uid": str(track.uid),
            "display_name": track.display_name,
        }

    def test_paper_conference_only_when_visible_but_not_admin(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        other_conference: Conference,
        other_track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        paper_other = make_paper(
            other_conference,
            other_track,
            conference_chair,
            "O-001",
        )
        make_match(report, paper_own, paper_other)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        pairs = response.json()["matches"][0]["pair"]
        other_paper = next(
            p for p in pairs if p.get("conference") == other_conference.name
        )
        assert other_paper["visibility"] == "conference_only"
        assert other_paper["uid"] == str(paper_other.uid)
        assert "title" not in other_paper
        assert "track" not in other_paper
        assert "code" not in other_paper
        assert "state" not in other_paper
        assert "create_time" not in other_paper
        assert "withdraw_time" not in other_paper

    def test_paper_redacted_when_not_visible(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        hidden_conference: Conference,
        hidden_track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        paper_hidden = make_paper(
            hidden_conference,
            hidden_track,
            conference_chair,
            "H-001",
        )
        make_match(report, paper_own, paper_hidden)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        pairs = response.json()["matches"][0]["pair"]
        redacted = next(p for p in pairs if p["visibility"] == "redacted")
        assert redacted["uid"] == str(paper_hidden.uid)
        assert "conference" not in redacted
        assert "title" not in redacted
        assert "track" not in redacted

    def test_cross_conference_match_mixed_visibility(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        hidden_conference: Conference,
        hidden_track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        paper_hidden = make_paper(
            hidden_conference,
            hidden_track,
            conference_chair,
            "H-001",
        )
        make_match(report, paper_own, paper_hidden)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        pairs = response.json()["matches"][0]["pair"]
        visibilities = {p["visibility"] for p in pairs}
        assert visibilities == {"visible", "redacted"}

    def test_cross_conference_match_conference_only(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        other_conference: Conference,
        other_track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        paper_other = make_paper(
            other_conference,
            other_track,
            conference_chair,
            "O-001",
        )
        make_match(report, paper_own, paper_other)

        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        pairs = response.json()["matches"][0]["pair"]
        visibilities = {p["visibility"] for p in pairs}
        assert visibilities == {"visible", "conference_only"}

    def test_unacknowledged_before_acknowledged(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        report: DuplicateReport,
    ) -> None:
        p1 = make_paper(conference, track, conference_chair, "P-001")
        p2 = make_paper(conference, track, conference_chair, "P-002")
        p3 = make_paper(conference, track, conference_chair, "P-003")
        p4 = make_paper(conference, track, conference_chair, "P-004")
        make_match(report, p1, p2, score=0.9)
        make_match(report, p3, p4, score=0.9)
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(p1, p2),
            conference=conference,
            user=conference_chair,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        [match1, match2] = response.json()["matches"]
        assert "acknowledgment" not in match1
        assert "acknowledgment" in match2

    def test_higher_score_first_within_same_ack_status(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        report: DuplicateReport,
    ) -> None:
        p1 = make_paper(conference, track, conference_chair, "P-001")
        p2 = make_paper(conference, track, conference_chair, "P-002")
        p3 = make_paper(conference, track, conference_chair, "P-003")
        p4 = make_paper(conference, track, conference_chair, "P-004")
        make_match(report, p1, p2, score=0.7)
        make_match(report, p3, p4, score=0.95)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        [match1, match2] = response.json()["matches"]
        assert match1["score"] == 0.95
        assert match2["score"] == 0.7

    def test_file_hash_before_title_similarity_at_same_score(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        report: DuplicateReport,
    ) -> None:
        p1 = make_paper(conference, track, conference_chair, "P-001")
        p2 = make_paper(conference, track, conference_chair, "P-002")
        p3 = make_paper(conference, track, conference_chair, "P-003")
        p4 = make_paper(conference, track, conference_chair, "P-004")
        make_match(
            report,
            p1,
            p2,
            match_type=DuplicateMatchType.TITLE_SIMILARITY,
            score=0.9,
        )
        make_match(
            report,
            p3,
            p4,
            match_type=DuplicateMatchType.FILE_HASH,
            score=0.9,
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        [match1, match2] = response.json()["matches"]
        assert match1["match_type"] == DuplicateMatchType.FILE_HASH
        assert match2["match_type"] == DuplicateMatchType.TITLE_SIMILARITY

    def test_match_with_acknowledgment(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        make_match(report, paper_a, paper_b)
        Profile.objects.create(
            user=conference_chair,
            given_name="Admin",
            family_name="Chair",
        )
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=conference_chair,
            note="Confirmed false positive.",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        ack = response.json()["matches"][0]["acknowledgment"]
        assert ack["create_time"] == any_str
        assert ack["update_time"] == any_str
        assert ack["note"] == "Confirmed false positive."
        assert ack["user"]["uid"] == str(conference_chair.uid)
        assert ack["user"]["profile"]["given_name"] == "Admin"
        assert ack["user"]["profile"]["family_name"] == "Chair"

    def test_match_without_acknowledgment(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        report: DuplicateReport,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        make_match(report, paper_a, paper_b)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        assert "acknowledgment" not in response.json()["matches"][0]

    def test_acknowledgment_scoped_to_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        other_conference: Conference,
        other_track: Track,
        report: DuplicateReport,
    ) -> None:
        """An ack on other_conference does not appear in conference's report."""
        paper_own = make_paper(conference, track, conference_chair, "P-001")
        paper_other = make_paper(
            other_conference,
            other_track,
            conference_chair,
            "O-001",
        )
        match = make_match(report, paper_own, paper_other)
        # Acknowledge the pair from the other conference's perspective.
        DuplicateAcknowledgment.objects.create(
            paper_a_id=match.paper_a_id,
            paper_b_id=match.paper_b_id,
            conference=other_conference,
            user=conference_chair,
            note="Other conference ack.",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))

        assert "acknowledgment" not in response.json()["matches"][0]

    def test_conference_not_found(self, api_client: Client, global_admin: User) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path("nonexistent"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        report: DuplicateReport,  # noqa: ARG002
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_no_successful_report_returns_404(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_only_failed_reports_returns_404(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        DuplicateReport.objects.create(state=DuplicateReportState.FAILED)
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        report: DuplicateReport,  # noqa: ARG002
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_global_read_all(
        self,
        api_client: Client,
        conference: Conference,
        global_read_all: User,
        report: DuplicateReport,  # noqa: ARG002
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        report: DuplicateReport,  # noqa: ARG002
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        api_client.force_login(track_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestUpdateDuplicateAcknowledgment:
    @classmethod
    def path(cls, conference_name: str, paper_uid_a: ULID, paper_uid_b: ULID) -> str:
        return reverse(
            "api-1.0.0:update-duplicate-acknowledgment",
            args=[conference_name, paper_uid_a, paper_uid_b],
        )

    def test_creates_new_acknowledgment(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        Profile.objects.create(
            user=conference_chair,
            given_name="Admin",
            family_name="Chair",
        )
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={"note": "Confirmed duplicate."},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["note"] == "Confirmed duplicate."
        assert data["create_time"] == approx_now()
        assert data["update_time"] == approx_now()
        assert data["user"]["uid"] == str(conference_chair.uid)
        assert data["user"]["profile"]["given_name"] == "Admin"

        assert conference.duplicate_acknowledgments.filter(
            paper_a=paper_a,
            paper_b=paper_b,
            note="Confirmed duplicate.",
        ).exists()

    def test_updates_existing_acknowledgment(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        ack = DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=conference_chair,
            note="Old note.",
        )
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={"note": "Updated note."},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["note"] == "Updated note."

        assert conference.duplicate_acknowledgments.count() == 1
        ack.refresh_from_db()
        assert ack.note == "Updated note."

    def test_empty_note_default(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        assert response.json()["note"] == ""

    def test_normalizes_paper_pair_order(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        """Passing UIDs in reverse order still creates a canonical pair."""
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(conference_chair)

        # Pass UIDs in reverse order (larger UID first).
        if paper_a.pk < paper_b.pk:
            path = self.path(conference.name, paper_b.uid, paper_a.uid)
        else:
            self.path(conference.name, paper_a.uid, paper_b.uid)
        response = api_client.put(path, data={})
        assert response.status_code == HTTPStatus.OK

        ack = DuplicateAcknowledgment.objects.get(conference=conference)
        assert ack.paper_a_id == min(paper_a.pk, paper_b.pk)
        assert ack.paper_b_id == max(paper_a.pk, paper_b.pk)

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path("nonexistent", paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, ULID()),
            data={},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        update_object(paper_b, delete_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        conference_chair: User,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(user)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, global_admin, "P-001")
        paper_b = make_paper(conference, track, global_admin, "P-002")
        api_client.force_login(global_admin)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(conference_chair)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, global_read_all, "P-001")
        paper_b = make_paper(conference, track, global_read_all, "P-002")
        api_client.force_login(global_read_all)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        paper_a = make_paper(conference, track, track_admin, "P-001")
        paper_b = make_paper(conference, track, track_admin, "P-002")
        api_client.force_login(track_admin)

        response = api_client.put(
            self.path(conference.name, paper_a.uid, paper_b.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestDeleteDuplicateAcknowledgment:
    @classmethod
    def path(cls, conference_name: str, paper_uid_a: ULID, paper_uid_b: ULID) -> str:
        return reverse(
            "api-1.0.0:delete-duplicate-acknowledgment",
            args=[conference_name, paper_uid_a, paper_uid_b],
        )

    def test_deletes_acknowledgment(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=conference_chair,
        )
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

        assert not conference.duplicate_acknowledgments.exists()

    def test_acknowledgment_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_acknowledgment_scoped_to_conference(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
        other_conference: Conference,
        other_track: Track,
    ) -> None:
        """Deleting from conference A does not find an ack belonging to conference B."""
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(other_conference, other_track, conference_chair, "O-001")
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=other_conference,
            user=conference_chair,
        )
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        # The other conference's ack should still exist.
        assert other_conference.duplicate_acknowledgments.exists()

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path("nonexistent", paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=conference_chair,
        )
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, ULID()),
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=conference_chair,
        )
        update_object(paper_b, delete_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_normalizes_paper_pair_order(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        """Passing UIDs in reverse order still finds the canonical ack."""
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=conference_chair,
        )
        api_client.force_login(conference_chair)

        # Pass UIDs in reverse order (larger PK first).
        if paper_a.pk < paper_b.pk:
            path = self.path(conference.name, paper_b.uid, paper_a.uid)
        else:
            path = self.path(conference.name, paper_a.uid, paper_b.uid)
        response = api_client.delete(path)
        assert response.status_code == HTTPStatus.NO_CONTENT

        assert not conference.duplicate_acknowledgments.exists()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        track: Track,
        conference_chair: User,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        api_client.force_login(user)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, global_admin, "P-001")
        paper_b = make_paper(conference, track, global_admin, "P-002")
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=global_admin,
        )
        api_client.force_login(global_admin)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, conference_chair, "P-001")
        paper_b = make_paper(conference, track, conference_chair, "P-002")
        DuplicateAcknowledgment.objects.create(
            **canonical_pair(paper_a, paper_b),
            conference=conference,
            user=conference_chair,
        )
        api_client.force_login(conference_chair)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_authorization_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper_a = make_paper(conference, track, global_read_all, "P-001")
        paper_b = make_paper(conference, track, global_read_all, "P-002")
        api_client.force_login(global_read_all)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_track_admin_forbidden(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        track: Track,
    ) -> None:
        track_admin = User.objects.create_user(username=faker.user_name())
        TrackRoleAssignment.objects.create(
            track=track,
            user=track_admin,
            role=TrackRole.CHAIR,
        )
        paper_a = make_paper(conference, track, track_admin, "P-001")
        paper_b = make_paper(conference, track, track_admin, "P-002")
        api_client.force_login(track_admin)

        response = api_client.delete(
            self.path(conference.name, paper_a.uid, paper_b.uid),
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
