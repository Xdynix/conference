from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import Conference, Paper, PaperDecision, Profile, Track
from app.conference.services import PaperService
from app.conference.services.paper import PaperStateError
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=Paper.State.ACCEPTED,
    )


def create_decision(
    paper: Paper,
    decider: User,
    state: PaperDecision.State = PaperDecision.State.ACCEPTED,
    note: str = "",
) -> PaperDecision:
    return PaperDecision.objects.create(
        paper=paper,
        decider=decider,
        state=state,
        note=note,
    )


@pytest.mark.django_db
class TestListPaperDecisions:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:list-paper-decisions",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        Profile.objects.create(
            user=conference_chair,
            given_name="Alice",
            family_name="Chair",
            affiliation="University",
        )
        decision = create_decision(
            paper,
            conference_chair,
            state=PaperDecision.State.ACCEPTED,
            note="Strong accept based on reviews.",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "create_time": any_str,
                "decider": {
                    "uid": str(conference_chair.uid),
                    "email": "",
                    "profile": {
                        "given_name": "Alice",
                        "family_name": "Chair",
                        "affiliation": "University",
                        "region_code": "",
                    },
                },
                "state": decision.state,
                "note": "Strong accept based on reviews.",
            },
        ]

    def test_returns_multiple_decisions_ordered_by_create_time_descending(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        decision1 = create_decision(
            paper,
            conference_chair,
            state=PaperDecision.State.REJECTED,
            note="Initial rejection",
        )
        decision2 = create_decision(
            paper,
            conference_chair,
            state=PaperDecision.State.ACCEPTED,
            note="Reconsidered and accepted",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        [data1, data2] = response.json()
        assert data1["note"] == decision2.note
        assert data2["note"] == decision1.note

    def test_returns_empty_list_when_no_decisions(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path("nonexistent", "PAPER-001"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, "NONEXISTENT"))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("global_role", [GlobalRole.ADMIN, GlobalRole.READ_ALL])
    def test_authorization_global_role(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        global_role: GlobalRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        GlobalRoleAssignment.objects.create(user=admin, role=global_role)
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

    def test_conference_secretary_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.fixture
def paper_service_decide(mocker: MockerFixture) -> MagicMock:
    return mocker.spy(PaperService, "decide_paper")


@pytest.mark.django_db
class TestDecidePaper:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:decide-paper",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_decide: MagicMock,
    ) -> None:
        update_object(paper, state=Paper.State.SUBMITTED)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={
                "state": "Accepted",
                "note": "Strong contribution to the field.",
            },
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code
        assert data["state"] == "Accepted"

        paper_service_decide.assert_called_once_with(
            paper=paper,
            decider=conference_chair,
            state=Paper.State.ACCEPTED,
            note="Strong contribution to the field.",
        )

    def test_defaults_note_to_empty_string(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_decide: MagicMock,
    ) -> None:
        update_object(paper, state=Paper.State.SUBMITTED)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Rejected"},
        )
        assert response.status_code == HTTPStatus.OK

        call_kwargs = paper_service_decide.call_args.kwargs
        assert call_kwargs["note"] == ""

    def test_handles_paper_state_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_decide: MagicMock,
    ) -> None:
        paper_service_decide.side_effect = PaperStateError(
            "Draft papers cannot be decided."
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        assert "Draft papers cannot be decided." in response.json()["message"]

    def test_validates_state_required(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_validates_state_enum(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "InvalidState"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", "PAPER-001"),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_inactive_conference_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(conference, active=False)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_deleted_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(paper, delete_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        paper_service_decide: MagicMock,
    ) -> None:
        paper_service_decide.return_value = paper
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_decide.assert_called_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        paper_service_decide: MagicMock,
    ) -> None:
        paper_service_decide.return_value = paper
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.OK

        paper_service_decide.assert_called_once()

    def test_authorization_conference_secretary_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_read_all_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        global_read_all: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"state": "Accepted"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
