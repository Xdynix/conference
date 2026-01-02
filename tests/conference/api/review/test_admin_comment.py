from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.conference.models import (
    AdminComment,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Paper,
    Profile,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, approx_now


def create_admin_comment(
    paper: Paper,
    author: User,
    content: str = "Test comment",
) -> AdminComment:
    return AdminComment.objects.create(
        paper=paper,
        author=author,
        content=content,
    )


@pytest.mark.django_db
class TestListAdminComments:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:list-admin-comments",
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
            family_name="Admin",
            affiliation="University",
        )
        comment = create_admin_comment(paper, conference_chair, "Great paper!")
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(comment.uid),
                "create_time": any_str,
                "author": {
                    "uid": str(conference_chair.uid),
                    "email": "",
                    "profile": {
                        "given_name": "Alice",
                        "family_name": "Admin",
                        "affiliation": "University",
                        "region_code": "",
                    },
                },
                "content": "Great paper!",
            },
        ]

    def test_returns_multiple_comments_ordered_by_uid(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment1 = create_admin_comment(paper, conference_chair, "First comment")
        comment2 = create_admin_comment(paper, conference_chair, "Second comment")
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        [data1, data2] = response.json()
        assert data1["uid"] == str(comment1.uid)
        assert data2["uid"] == str(comment2.uid)

    def test_returns_empty_list_when_no_comments(
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

    def test_author_can_be_null(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment = AdminComment.objects.create(
            paper=paper,
            author=None,
            content="Anonymous comment",
        )
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

        [data] = response.json()
        assert data["uid"] == str(comment.uid)
        assert "author" not in data

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

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.get(self.path(conference.name, paper.code))
        assert response.status_code == HTTPStatus.OK

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


@pytest.mark.django_db
class TestCreateAdminComment:
    @classmethod
    def path(cls, conference_name: str, paper_code: str) -> str:
        return reverse(
            "api-1.0.0:create-admin-comment",
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
            family_name="Admin",
        )
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"content": "This paper needs revision."},
        )
        assert response.status_code == HTTPStatus.CREATED

        assert response.json() == {
            "uid": any_str,
            "create_time": approx_now(),
            "author": {
                "uid": str(conference_chair.uid),
                "email": conference_chair.email,
                "profile": {
                    "given_name": "Alice",
                    "family_name": "Admin",
                    "affiliation": "",
                    "region_code": "",
                },
            },
            "content": "This paper needs revision.",
        }

        comment = AdminComment.objects.get(paper=paper)
        assert comment.author == conference_chair
        assert comment.content == "This paper needs revision."

    def test_content_strip_whitespaces(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"content": "   Content   "},
        )
        assert response.status_code == HTTPStatus.CREATED

        comment = AdminComment.objects.get(paper=paper)
        assert comment.content == "   Content"

    def test_content_required(
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

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "content"]

    def test_content_cannot_be_empty(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"content": "   \n"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        data = response.json()
        [error] = data["details"]
        assert error["loc"] == ["body", "payload", "content"]

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path("nonexistent", "PAPER-001"),
            data={"content": "Comment"},
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
            data={"content": "Comment"},
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
            data={"content": "Comment"},
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
            data={"content": "Comment"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_global_admin_can_access(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"content": "Admin comment"},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
        paper: Paper,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"content": "Comment"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        paper: Paper,
        conference_role: ConferenceRole,
    ) -> None:
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"content": "Comment"},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        paper: Paper,
    ) -> None:
        api_client.force_login(conference_reviewer)

        response = api_client.post(
            self.path(conference.name, paper.code),
            data={"content": "Comment"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestDeleteAdminComment:
    @classmethod
    def path(cls, conference_name: str, comment_uid: ULID) -> str:
        return reverse(
            "api-1.0.0:delete-admin-comment",
            args=[conference_name, comment_uid],
        )

    def test_happy_path(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment = create_admin_comment(paper, conference_chair)
        api_client.force_login(conference_chair)

        response = api_client.delete(self.path(conference.name, comment.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

        assert not AdminComment.objects.filter(pk=comment.pk).exists()

    def test_conference_not_found(
        self,
        api_client: Client,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.delete(self.path("nonexistent", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_comment_not_found(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.delete(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_comment_from_other_conference_not_found(
        self,
        faker: Faker,
        api_client: Client,
        global_admin: User,
        paper: Paper,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        comment = create_admin_comment(paper, global_admin)
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(other_conference.name, comment.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

        assert AdminComment.objects.filter(pk=comment.pk).exists()

    def test_authorization_unauthenticated(
        self,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment = create_admin_comment(paper, conference_chair)

        response = api_client.delete(self.path(conference.name, comment.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

        assert AdminComment.objects.filter(pk=comment.pk).exists()

    def test_authorization_user_without_roles(
        self,
        api_client: Client,
        user: User,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment = create_admin_comment(paper, conference_chair)
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, comment.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert AdminComment.objects.filter(pk=comment.pk).exists()

    def test_global_admin_can_access(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment = create_admin_comment(paper, conference_chair)
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, comment.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment = create_admin_comment(paper, conference_chair)
        api_client.force_login(global_read_all)

        response = api_client.delete(self.path(conference.name, comment.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    def test_authorization_conference_admin(
        self,
        faker: Faker,
        api_client: Client,
        conference: Conference,
        conference_chair: User,
        paper: Paper,
        conference_role: ConferenceRole,
    ) -> None:
        comment = create_admin_comment(paper, conference_chair)
        admin = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=admin,
            role=conference_role,
        )
        api_client.force_login(admin)

        response = api_client.delete(self.path(conference.name, comment.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_conference_reviewer_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        conference_reviewer: User,
        conference_chair: User,
        paper: Paper,
    ) -> None:
        comment = create_admin_comment(paper, conference_chair)
        api_client.force_login(conference_reviewer)

        response = api_client.delete(self.path(conference.name, comment.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

        assert AdminComment.objects.filter(pk=comment.pk).exists()
