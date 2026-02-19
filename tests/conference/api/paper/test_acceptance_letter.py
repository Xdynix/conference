from collections.abc import Coroutine
from http import HTTPStatus
from pathlib import Path
from typing import Any, NoReturn
from unittest.mock import MagicMock

import pytest
from django.conf import LazySettings
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_mock import MockerFixture
from ulid import ULID

from app.conference.models import (
    AcceptanceLetter,
    Conference,
    IEEEeCopyrightConfig,
    Paper,
    PaperAuthor,
    PaperState,
    Profile,
    Track,
)
from app.core.models import User
from app.utils.enums import Region
from app.utils.typst import CompilationError
from tests.helpers import update_object

FAKE_PDF = b"%PDF-fake-acceptance"
TEMPLATE = "#set page(width: auto)\nHello, world!"


@pytest.fixture
def paper(conference: Conference, track: Track, user: User) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        owner=user,
        code="PAPER-001",
        title="Test Paper",
        state=PaperState.ACCEPTED,
    )


@pytest.fixture
def compile_template(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "app.conference.api.paper.acceptance_letter.compile_template",
        return_value=FAKE_PDF,
    )


@pytest.fixture(autouse=True)
def file_download_mode(settings: LazySettings) -> None:
    settings.FILE_DOWNLOAD_MODE = "django"


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
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(paper.uid)
        assert data["code"] == paper.code

        compile_template.assert_called_once()
        call_args = compile_template.call_args
        assert call_args[0][0] == TEMPLATE

        letter = AcceptanceLetter.objects.get(paper=paper)
        assert letter.template == TEMPLATE
        assert letter.rendered_pdf.name

    def test_accepted_revision_needed_allowed(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        update_object(paper, state=PaperState.ACCEPTED_REVISION_NEEDED)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_context_structure(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        Profile.objects.create(
            user=paper.owner,
            given_name="Alice",
            family_name="Smith",
            affiliation="MIT",
            region_code="US",
        )
        PaperAuthor.objects.create(
            paper=paper,
            given_name="Bob",
            family_name="Jones",
            affiliation="Stanford",
            region_code="US",
            email="bob@example.com",
            phone="+1234567890",
            corresponding=True,
            ordering=1,
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]
        assert context["conference"]["name"] == conference.name
        assert context["conference"]["display_name"] == conference.display_name
        assert context["track"]["display_name"] == track.display_name
        assert context["track"]["ieee_ecopyright_required"] is False
        assert context["paper"]["code"] == paper.code
        assert context["paper"]["title"] == paper.title
        assert context["paper"]["user"]["given_name"] == "Alice"
        assert context["paper"]["user"]["family_name"] == "Smith"
        assert context["paper"]["user"]["region_name"] == Region.get_label("US")
        assert len(context["paper"]["authors"]) == 1
        author = context["paper"]["authors"][0]
        assert author["given_name"] == "Bob"
        assert author["corresponding"] is True
        assert context["extra"] == {}

    def test_extra_context(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)
        extra = {"registration_due": "2026-04-01", "note": "Early bird"}

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE, "extra_context": extra},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]
        assert context["extra"] == extra

        letter = AcceptanceLetter.objects.get(paper=paper)
        assert letter.context["extra"] == extra

    def test_ieee_ecopyright_required(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Test Publication",
            article_source="Test Source",
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]
        assert context["track"]["ieee_ecopyright_required"] is True

    def test_ieee_ecopyright_exempt_track(
        self,
        api_client: Client,
        conference: Conference,
        track: Track,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        config = IEEEeCopyrightConfig.objects.create(
            conference=conference,
            publication_title="Test Publication",
            article_source="Test Source",
        )
        config.exempt_tracks.add(track)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        context = compile_template.call_args[0][1]
        assert context["track"]["ieee_ecopyright_required"] is False

    def test_regeneration_replaces_existing(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "first template"},
        )
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "second template"},
        )
        assert response.status_code == HTTPStatus.OK
        assert AcceptanceLetter.objects.filter(paper=paper).count() == 1

        letter = AcceptanceLetter.objects.get(paper=paper)
        assert letter.template == "second template"

        compile_template.assert_called()

    @pytest.mark.django_db(transaction=True)
    def test_regeneration_deletes_old_file(
        self,
        api_client: Client,
        media_root: Path,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "first template"},
        )
        old_letter = AcceptanceLetter.objects.get(paper=paper)
        old_file = media_root / old_letter.rendered_pdf.name
        assert old_file.exists()

        compile_template.return_value = b"%PDF-second"
        api_client.post(
            self.path(conference.name, paper.code),
            data={"template": "second template"},
        )

        new_letter = AcceptanceLetter.objects.get(paper=paper)
        new_file = media_root / new_letter.rendered_pdf.name
        assert new_file.exists()
        assert not old_file.exists()

    def test_withdrawn_paper_rejected(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        update_object(paper, withdraw_time=timezone.now())
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "withdrawn" in response.json()["message"].lower()
        compile_template.assert_not_called()

    @pytest.mark.parametrize(
        "state",
        [
            PaperState.DRAFT,
            PaperState.SUBMITTED,
            PaperState.UNDER_REVIEW,
            PaperState.REJECTED,
        ],
    )
    def test_non_accepted_state_rejected(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
        state: PaperState,
    ) -> None:
        update_object(paper, state=state)
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        compile_template.assert_not_called()

    def test_compilation_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        compile_template.side_effect = CompilationError(
            "undefined variable",
            diagnostic="error at line 1",
            hints=[],
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "undefined variable" in error["msg"]

    def test_compilation_timeout(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch(
            "app.conference.api.paper.acceptance_letter.compile_template",
            return_value=FAKE_PDF,
        )

        async def raise_timeout(
            coro: Coroutine[Any, Any, Any],
            *_: Any,
            **__: Any,
        ) -> NoReturn:
            coro.close()
            raise TimeoutError

        mocker.patch(
            "app.conference.api.paper.acceptance_letter.asyncio.wait_for",
            side_effect=raise_timeout,
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "timed out" in error["msg"].lower()

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

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", "PAPER-001"),
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_paper_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, "NONEXISTENT"),
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

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
            data={"template": TEMPLATE},
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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestGetAcceptanceLetter:
    @classmethod
    def path(cls, uid: ULID) -> str:
        return reverse("api-1.0.0:get-acceptance-letter", args=[uid])

    def test_happy_path(
        self,
        api_client: Client,
        paper: Paper,
    ) -> None:
        letter = AcceptanceLetter.objects.create(
            paper=paper,
            template=TEMPLATE,
            context={},
        )
        letter.rendered_pdf.save(
            "acceptance-letter.pdf", ContentFile(FAKE_PDF), save=True
        )

        response = api_client.get(self.path(paper.uid))
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "application/pdf"
        assert b"".join(response.streaming_content) == FAKE_PDF  # type: ignore[attr-defined]

    def test_not_found(self, api_client: Client) -> None:
        response = api_client.get(self.path(ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_letter_not_generated(self, api_client: Client, paper: Paper) -> None:
        response = api_client.get(self.path(paper.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_missing_file_returns_not_found(
        self,
        api_client: Client,
        media_root: Path,
        paper: Paper,
    ) -> None:
        letter = AcceptanceLetter.objects.create(
            paper=paper,
            template=TEMPLATE,
            context={},
        )
        letter.rendered_pdf.save(
            "acceptance-letter.pdf", ContentFile(FAKE_PDF), save=True
        )
        file_path = media_root / letter.rendered_pdf.name
        file_path.unlink()

        response = api_client.get(self.path(paper.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestGetAcceptanceLetterDecorated:
    @classmethod
    def path(cls, uid: ULID, filename: str) -> str:
        return reverse("api-1.0.0:get-acceptance-letter-ex", args=[uid, filename])

    def test_happy_path(
        self,
        api_client: Client,
        paper: Paper,
    ) -> None:
        letter = AcceptanceLetter.objects.create(
            paper=paper,
            template=TEMPLATE,
            context={},
        )
        letter.rendered_pdf.save(
            "acceptance-letter.pdf", ContentFile(FAKE_PDF), save=True
        )

        response = api_client.get(self.path(paper.uid, "letter.pdf"))
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "application/pdf"
        assert b"".join(response.streaming_content) == FAKE_PDF  # type: ignore[attr-defined]

    def test_not_found(self, api_client: Client) -> None:
        response = api_client.get(self.path(ULID(), "letter.pdf"))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestPreviewAcceptanceLetter:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:preview-acceptance-letter",
            args=[conference_name, paper_code],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"] == "application/pdf"
        assert response.content == FAKE_PDF

        compile_template.assert_called_once()

    def test_no_save(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK
        assert not AcceptanceLetter.objects.exists()

        compile_template.assert_called_once()

    def test_compilation_error(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        compile_template.side_effect = CompilationError(
            "undefined variable",
            diagnostic="error at line 1",
            hints=[],
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        [error] = response.json()["details"]
        assert error["loc"] == ["body", "payload", "template"]
        assert "undefined variable" in error["msg"]

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        paper: Paper,
    ) -> None:
        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_authorization_global_admin(
        self,
        api_client: Client,
        conference: Conference,
        global_admin: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_chair(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

    def test_authorization_conference_secretary(
        self,
        api_client: Client,
        conference: Conference,
        conference_secretary: User,
        paper: Paper,
        compile_template: MagicMock,
    ) -> None:
        api_client.force_login(conference_secretary)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.OK

        compile_template.assert_called_once()

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
            data={"template": TEMPLATE},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
