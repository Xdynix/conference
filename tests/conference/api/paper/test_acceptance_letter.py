from http import HTTPStatus
from textwrap import dedent

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from ulid import ULID

from app.conference.models import (
    AcceptanceLetter,
    Conference,
    Paper,
    PaperAuthor,
    PaperState,
    Track,
)
from app.core.models import User
from tests.helpers import update_object


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    paper = Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="A Novel Approach to Machine Learning",
        state=PaperState.ACCEPTED,
    )
    PaperAuthor.objects.create(
        paper=paper,
        given_name="Alice",
        family_name="Smith",
        affiliation="University of Testing",
        ordering=0,
    )
    PaperAuthor.objects.create(
        paper=paper,
        given_name="Bob",
        family_name="Jones",
        affiliation="Institute of Science",
        ordering=1,
    )
    return paper


@pytest.mark.django_db
class TestGenerateAcceptanceLetter:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:generate-acceptance-letter",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        template = dedent(
            """<html>
            <body>
            <h1>Acceptance Letter</h1>
            <p>Dear Authors,</p>
            <p>We are pleased to inform you that your paper
            "{{ paper.title }}" ({{ paper.code }}) has been accepted
            to {{ paper.conference.display_name }}.</p>
            <h2>Authors</h2>
            <ul>
            {% for author in paper.authors.all() -%}
            <li>
                {{ author.given_name }} {{ author.family_name }}
                ({{ author.affiliation }})
            </li>
            {% endfor -%}
            </ul>
            </body>
            </html>"""
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": template},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code

        letter = AcceptanceLetter.objects.get(paper=paper)
        expected_html = dedent(
            f"""<html>
            <body>
            <h1>Acceptance Letter</h1>
            <p>Dear Authors,</p>
            <p>We are pleased to inform you that your paper
            "A Novel Approach to Machine Learning" (PAPER-001) has been accepted
            to {conference.display_name}.</p>
            <h2>Authors</h2>
            <ul>
            <li>
                Alice Smith
                (University of Testing)
            </li>
            <li>
                Bob Jones
                (Institute of Science)
            </li>
            </ul>
            </body>
            </html>"""
        )
        assert letter.rendered_html == expected_html

    def test_regenerating_replaces_existing_letter(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        AcceptanceLetter.objects.create(paper=paper, rendered_html="<p>Old</p>")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "<p>{{ paper.code }}</p>"},
        )
        assert response.status_code == HTTPStatus.OK

        assert AcceptanceLetter.objects.filter(paper=paper).count() == 1
        letter = AcceptanceLetter.objects.get(paper=paper)
        assert letter.rendered_html == "<p>PAPER-001</p>"

    def test_escapes_html_in_template_variables(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(paper, title="<script>alert('xss')</script>")
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "<p>{{ paper.title }}</p>"},
        )
        assert response.status_code == HTTPStatus.OK

        letter = AcceptanceLetter.objects.get(paper=paper)
        assert (
            letter.rendered_html
            == "<p>&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;</p>"
        )

    def test_template_syntax_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ unclosed"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "unexpected" in response.json()["message"].lower()

    def test_undefined_variable_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ undefined_var }}"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "undefined_var" in error["msg"]

    @pytest.mark.parametrize(
        "state",
        [
            PaperState.DRAFT,
            PaperState.SUBMITTED,
            PaperState.UNDER_REVIEW,
            PaperState.REJECTED,
        ],
    )
    def test_rejects_non_accepted_paper_state(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ paper.code }}"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert state.value in response.json()["message"]

    @pytest.mark.parametrize(
        "state",
        [PaperState.ACCEPTED, PaperState.ACCEPTED_REVISION_NEEDED],
    )
    def test_allows_accepted_paper_states(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ paper.code }}"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_rejects_withdrawn_paper(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ paper.code }}"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "withdrawn" in response.json()["message"].lower()

    def test_validates_template_required(
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

    def test_validates_template_not_empty(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": ""},
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
            data={"template": "test"},
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
            data={"template": "test"},
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
            data={"template": "test"},
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
            data={"template": "test"},
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
            data={"template": "test"},
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
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ paper.code }}"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ paper.code }}"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "{{ paper.code }}"},
        )
        assert response.status_code == HTTPStatus.OK

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
            data={"template": "test"},
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
            data={"template": "test"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestGetAcceptanceLetter:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:get-acceptance-letter", args=[uid])

    def test_happy_path(
        self,
        client: Client,
        paper: Paper,
    ) -> None:
        AcceptanceLetter.objects.create(
            paper=paper,
            rendered_html="<html><body><h1>Congratulations!</h1></body></html>",
        )

        response = client.get(self.path(paper.uid))

        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "text/html"
        assert (
            response.content == b"<html><body><h1>Congratulations!</h1></body></html>"
        )

    def test_returns_full_rendered_content(
        self,
        client: Client,
        paper: Paper,
    ) -> None:
        html_content = dedent(
            """<!DOCTYPE html>
            <html>
            <head><title>Acceptance Letter</title></head>
            <body>
            <h1>Dear Authors,</h1>
            <p>Your paper has been accepted.</p>
            <script>console.log('loaded');</script>
            </body>
            </html>
            """
        )
        AcceptanceLetter.objects.create(paper=paper, rendered_html=html_content)

        response = client.get(self.path(paper.uid))

        assert response.status_code == HTTPStatus.OK
        assert response.content.decode() == html_content

    def test_letter_not_found(self, client: Client, paper: Paper) -> None:
        response = client.get(self.path(paper.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found(self, client: Client) -> None:
        response = client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND
