from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from faker import Faker
from ulid import ULID

from app.conference.models import (
    CodePool,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from tests.helpers import any_str, approx_now


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
        visibility=Conference.Visibility.PUBLIC,
    )


@pytest.fixture
def global_admin(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.ADMIN)
    return user


@pytest.fixture
def global_read_all(faker: Faker) -> User:
    user = User.objects.create_user(username=faker.user_name())
    GlobalRoleAssignment.objects.create(user=user, role=GlobalRole.READ_ALL)
    return user


@pytest.fixture
def conference_chair(faker: Faker, conference: Conference) -> User:
    user = User.objects.create_user(username=faker.user_name())
    ConferenceRoleAssignment.objects.create(
        conference=conference,
        user=user,
        role=ConferenceRole.CHAIR,
    )
    return user


@pytest.mark.django_db
class TestListCodePools:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:list-code-pools", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool_b = CodePool.objects.create(
            conference=conference,
            name="Workshop Pool",
            prefix="WS",
        )
        pool_a = CodePool.objects.create(
            conference=conference,
            name="Main Pool",
            prefix="CONF",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == [
            {
                "uid": str(pool_a.uid),
                "name": "Main Pool",
                "prefix": "CONF",
                "next_sequence": 1,
                "create_time": approx_now(),
                "update_time": approx_now(),
            },
            {
                "uid": str(pool_b.uid),
                "name": "Workshop Pool",
                "prefix": "WS",
                "next_sequence": 1,
                "create_time": approx_now(),
                "update_time": approx_now(),
            },
        ]

    def test_returns_empty_list_when_no_pools(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        assert response.json() == []

    def test_scopes_pools_to_conference(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        pool = CodePool.objects.create(
            conference=conference,
            name="Target Pool",
            prefix="TGT",
        )
        CodePool.objects.create(
            conference=other_conference,
            name="Other Pool",
            prefix="OTH",
        )
        api_client.force_login(global_admin)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        [pool_data] = data
        assert pool_data["uid"] == str(pool.uid)

    def test_global_read_all_authorized(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.OK

    def test_chair_of_other_conference_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.get(self.path(conference.name))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.get(self.path("nonexistent-conf"))
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestCreateCodePool:
    @classmethod
    def path(cls, conference_name: str) -> str:
        return reverse("api-1.0.0:create-code-pool", args=[conference_name])

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "Main Pool", "prefix": "CONF"},
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data == {
            "uid": any_str,
            "name": "Main Pool",
            "prefix": "CONF",
            "next_sequence": 1,
            "create_time": approx_now(),
            "update_time": approx_now(),
        }

        assert CodePool.objects.filter(uid=data["uid"]).exists()

    def test_trims_whitespace(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "  Main Pool  ", "prefix": "  CONF  "},
        )
        assert response.status_code == HTTPStatus.CREATED

        data = response.json()
        assert data["name"] == "Main Pool"
        assert data["prefix"] == "CONF"

    def test_duplicate_prefix_conflict(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        CodePool.objects.create(
            conference=conference,
            name="Existing Pool",
            prefix="CONF",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "New Pool", "prefix": "CONF"},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "already exists" in response.json()["message"]

    def test_same_prefix_different_conference_allowed(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        CodePool.objects.create(
            conference=other_conference,
            name="Other Pool",
            prefix="CONF",
        )
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "New Pool", "prefix": "CONF"},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(conference_chair)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "Chair Pool", "prefix": "CHR"},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_read_all)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "Test Pool", "prefix": "TST"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "Test Pool", "prefix": "TST"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        response = api_client.post(
            self.path(conference.name),
            data={"name": "Test Pool", "prefix": "TST"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "Test Pool", "prefix": "TST"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path("nonexistent-conf"),
            data={"name": "Test Pool", "prefix": "TST"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_empty_name_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "", "prefix": "CONF"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_empty_prefix_rejected(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.post(
            self.path(conference.name),
            data={"name": "Test Pool", "prefix": ""},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
class TestUpdateCodePool:
    @classmethod
    def path(cls, conference_name: str, code_pool_id: ULID) -> str:
        return reverse(
            "api-1.0.0:update-code-pool",
            args=[conference_name, code_pool_id],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original Name",
            prefix="ORIG",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "Updated Name", "prefix": "UPD"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["uid"] == str(pool.uid)
        assert data["name"] == "Updated Name"
        assert data["prefix"] == "UPD"

        pool.refresh_from_db()
        assert pool.name == "Updated Name"
        assert pool.prefix == "UPD"

    def test_partial_update_name_only(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original Name",
            prefix="ORIG",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "New Name"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["name"] == "New Name"
        assert data["prefix"] == "ORIG"

    def test_partial_update_prefix_only(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original Name",
            prefix="ORIG",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"prefix": "NEW"},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["name"] == "Original Name"
        assert data["prefix"] == "NEW"

    def test_empty_payload_keeps_existing(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original Name",
            prefix="ORIG",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["name"] == "Original Name"
        assert data["prefix"] == "ORIG"

    def test_trims_whitespace(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original",
            prefix="ORIG",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "  Trimmed  ", "prefix": "  TRM  "},
        )
        assert response.status_code == HTTPStatus.OK

        data = response.json()
        assert data["name"] == "Trimmed"
        assert data["prefix"] == "TRM"

    def test_duplicate_prefix_conflict(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        CodePool.objects.create(
            conference=conference,
            name="Existing Pool",
            prefix="EXIST",
        )
        pool = CodePool.objects.create(
            conference=conference,
            name="Target Pool",
            prefix="TARGET",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"prefix": "EXIST"},
        )
        assert response.status_code == HTTPStatus.CONFLICT

        assert "already exists" in response.json()["message"]

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original",
            prefix="ORIG",
        )
        api_client.force_login(conference_chair)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.OK

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original",
            prefix="ORIG",
        )
        api_client.force_login(global_read_all)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        pool = CodePool.objects.create(
            conference=conference,
            name="Original",
            prefix="ORIG",
        )
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original",
            prefix="ORIG",
        )

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Original",
            prefix="ORIG",
        )
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_pool_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, ULID()),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_pool_from_different_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        pool = CodePool.objects.create(
            conference=other_conference,
            name="Other Pool",
            prefix="OTH",
        )
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path(conference.name, pool.uid),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.patch(
            self.path("nonexistent-conf", ULID()),
            data={"name": "Updated"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
class TestDeleteCodePool:
    @classmethod
    def path(cls, conference_name: str, code_pool_id: ULID) -> str:
        return reverse(
            "api-1.0.0:delete-code-pool",
            args=[conference_name, code_pool_id],
        )

    def test_happy_path(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="To Delete",
            prefix="DEL",
        )
        pool_uid = pool.uid
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

        assert not CodePool.objects.filter(uid=pool_uid).exists()

    def test_protected_by_track_conflict(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="Protected Pool",
            prefix="PROT",
        )
        Track.objects.create(
            conference=conference,
            display_name="Track with Pool",
            code_pool=pool,
        )
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.CONFLICT

        assert "referenced" in response.json()["message"]
        assert CodePool.objects.filter(uid=pool.uid).exists()

    def test_conference_chair_authorized(
        self,
        api_client: Client,
        conference_chair: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="To Delete",
            prefix="DEL",
        )
        api_client.force_login(conference_chair)

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_global_read_all_forbidden(
        self,
        api_client: Client,
        global_read_all: User,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="To Delete",
            prefix="DEL",
        )
        api_client.force_login(global_read_all)

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_chair_of_other_conference_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        user = User.objects.create_user(username=faker.user_name())
        ConferenceRoleAssignment.objects.create(
            conference=other_conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        pool = CodePool.objects.create(
            conference=conference,
            name="To Delete",
            prefix="DEL",
        )
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unauthenticated_user_unauthorized(
        self,
        api_client: Client,
        conference: Conference,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="To Delete",
            prefix="DEL",
        )

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unauthorized_user_forbidden(
        self,
        api_client: Client,
        conference: Conference,
        faker: Faker,
    ) -> None:
        pool = CodePool.objects.create(
            conference=conference,
            name="To Delete",
            prefix="DEL",
        )
        user = User.objects.create_user(username=faker.user_name())
        api_client.force_login(user)

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_pool_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_pool_from_different_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
        conference: Conference,
        faker: Faker,
    ) -> None:
        other_conference = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        pool = CodePool.objects.create(
            conference=other_conference,
            name="Other Pool",
            prefix="OTH",
        )
        api_client.force_login(global_admin)

        response = api_client.delete(self.path(conference.name, pool.uid))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_conference_not_found(
        self,
        api_client: Client,
        global_admin: User,
    ) -> None:
        api_client.force_login(global_admin)

        response = api_client.delete(self.path("nonexistent-conf", ULID()))
        assert response.status_code == HTTPStatus.NOT_FOUND
