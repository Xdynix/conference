from abc import ABC
from unittest.mock import AsyncMock

import pytest
from django.test import Client
from faker import Faker
from ninja import NinjaAPI
from pytest_mock import MockerFixture

from app.conference.auth import (
    has_any_conference_or_track_roles,
    has_any_conference_roles,
    has_any_track_roles,
)
from app.conference.models import (
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import ConferenceService
from app.core.auth import SessionAuth
from app.core.models import User
from app.core.types import HttpRequest
from tests.base import ResponseAssertionsMixin, URLConfTestCase, URLPatterns
from tests.helpers import update_object


class BaseAuthTestCase(ResponseAssertionsMixin, URLConfTestCase, ABC):
    auth: SessionAuth

    @pytest.fixture
    def user(self, faker: Faker) -> User:
        return User.objects.create_user(username=faker.user_name())

    @pytest.fixture
    def conference(self, faker: Faker) -> Conference:
        return Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def track(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.sentence(),
        )

    @pytest.fixture
    def visible_conferences(self, mocker: MockerFixture) -> AsyncMock:
        return mocker.patch.object(ConferenceService, "visible_conferences")

    @pytest.fixture
    def visible_tracks(self, mocker: MockerFixture) -> AsyncMock:
        return mocker.patch.object(ConferenceService, "visible_tracks")


class ConferenceAuthTestCase(BaseAuthTestCase):
    path_template = "/auth/conference/{conference_name}"

    @classmethod
    def path(cls, conference_name: str) -> str:
        return cls.path_template.format(conference_name=conference_name)

    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        @api.get(self.path_template, auth=self.auth)
        async def view(request: HttpRequest, conference_name: str) -> str:
            assert request
            assert conference_name
            return "OK"

        # Intentionally imported as local to prevent it
        # from occupying the global namespace.
        from django.urls import path

        return [path("", api.urls)]


@pytest.mark.django_db
class TestHasAnyConferenceRoles(ConferenceAuthTestCase):
    auth = has_any_conference_roles(ConferenceRole.CHAIR)

    def test_superuser_allowed(
        self,
        client: Client,
        user: User,
        visible_conferences: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.none()
        update_object(user, is_superuser=True)
        client.force_login(user)

        response = client.get(self.path("any"))

        self.assert_response_is_ok(response)
        visible_conferences.assert_not_called()

    def test_allows_user_with_matching_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)

    def test_forbids_user_without_required_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)

    def test_returns_404_when_conference_invisible_even_with_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.none()
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_not_found(response)
        visible_conferences.assert_awaited_once_with(user)


@pytest.mark.django_db
class TestHasAnyConferenceRolesMultiple(ConferenceAuthTestCase):
    auth = has_any_conference_roles(ConferenceRole.CHAIR, ConferenceRole.REVIEWER)

    def test_allows_user_with_any_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.REVIEWER,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)

    def test_forbids_user_without_any_required_roles(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)


class TrackAuthTestCase(BaseAuthTestCase):
    path_template = "/auth/conference/{conference_name}/tracks/{track_id}"

    @classmethod
    def path(cls, conference_name: str, track_id: str) -> str:
        return cls.path_template.format(
            conference_name=conference_name,
            track_id=track_id,
        )

    @pytest.fixture
    def urlpatterns(self, api: NinjaAPI) -> URLPatterns:
        @api.get(self.path_template, auth=self.auth)
        async def view(
            request: HttpRequest,
            conference_name: str,
            track_id: str,
        ) -> str:
            assert request
            assert conference_name
            assert track_id
            return "OK"

        from django.urls import path

        return [path("", api.urls)]

    @pytest.fixture
    def track(self, faker: Faker, conference: Conference) -> Track:
        return Track.objects.create(
            conference=conference,
            display_name=faker.sentence(),
        )


@pytest.mark.django_db
class TestHasAnyTrackRoles(TrackAuthTestCase):
    auth = has_any_track_roles(TrackRole.CHAIR)

    def test_superuser_allowed(
        self,
        client: Client,
        user: User,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.none()
        visible_tracks.return_value = Track.objects.none()
        update_object(user, is_superuser=True)
        client.force_login(user)

        response = client.get(self.path("any", "track"))

        self.assert_response_is_ok(response)
        visible_conferences.assert_not_called()
        visible_tracks.assert_not_called()

    def test_allows_user_with_matching_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_forbids_user_without_required_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.SECRETARY,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_returns_404_when_conference_invisible_even_with_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.none()
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_not_found(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_not_called()

    def test_returns_404_when_track_invisible_even_with_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.none()
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_not_found(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])


@pytest.mark.django_db
class TestHasAnyTrackRolesMultiple(TrackAuthTestCase):
    auth = has_any_track_roles(TrackRole.CHAIR, TrackRole.REVIEWER)

    def test_allows_user_with_any_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.REVIEWER,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_forbids_user_without_any_required_roles(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.SECRETARY,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])


@pytest.mark.django_db
class TestHasAnyConferenceOrTrackRoles(ConferenceAuthTestCase):
    auth = has_any_conference_or_track_roles(
        ConferenceRole.CHAIR,
        TrackRole.CHAIR,
    )

    def test_superuser_allowed(
        self,
        client: Client,
        user: User,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.none()
        visible_tracks.return_value = Track.objects.none()
        update_object(user, is_superuser=True)
        client.force_login(user)

        response = client.get(self.path("any"))

        self.assert_response_is_ok(response)
        visible_conferences.assert_not_called()
        visible_tracks.assert_not_called()

    def test_allows_user_with_conference_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.none()
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_not_called()

    def test_allows_user_with_track_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_forbids_user_without_required_roles(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.SECRETARY,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_returns_404_when_conference_invisible_even_with_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.none()
        visible_tracks.return_value = Track.objects.none()
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_not_found(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_not_called()

    def test_returns_forbidden_when_track_invisible_even_with_track_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.none()
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])


@pytest.mark.django_db
class TestHasAnyConferenceOrTrackRolesMultiple(ConferenceAuthTestCase):
    auth = has_any_conference_or_track_roles(
        ConferenceRole.CHAIR,
        ConferenceRole.SECRETARY,
        TrackRole.CHAIR,
        TrackRole.REVIEWER,
    )

    def test_allows_user_with_any_conference_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.none()
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_not_called()

    def test_allows_user_with_any_track_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.REVIEWER,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_forbids_user_without_any_required_roles(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.REVIEWER,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_forbids_user_when_track_invisible_even_with_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.none()
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_returns_404_when_conference_invisible_even_with_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.none()
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_not_found(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_not_called()


@pytest.mark.django_db
class TestHasAnyConferenceOrTrackRolesOnlyConferenceRole(ConferenceAuthTestCase):
    auth = has_any_conference_or_track_roles(ConferenceRole.CHAIR)

    def test_forbids_user_with_only_track_role(
        self,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.filter(pk=track.pk)
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_not_called()


@pytest.mark.django_db
class TestHasAnyConferenceOrTrackRolesOnlyTrackRole(ConferenceAuthTestCase):
    auth = has_any_conference_or_track_roles(TrackRole.CHAIR)

    def test_forbids_user_with_only_conference_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        visible_conferences: AsyncMock,
        visible_tracks: AsyncMock,
    ) -> None:
        visible_conferences.return_value = Conference.objects.filter(pk=conference.pk)
        visible_tracks.return_value = Track.objects.none()
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        visible_conferences.assert_awaited_once_with(user)
        visible_tracks.assert_awaited_once_with(user, [mocker.ANY])
