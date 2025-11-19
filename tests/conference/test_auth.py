from abc import ABC

import pytest
from django.test import Client
from faker import Faker
from ninja import NinjaAPI
from pytest_mock import MockerFixture

from app.conference.auth import has_any_conference_roles, has_any_track_roles
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
        mocker: MockerFixture,
        client: Client,
        user: User,
    ) -> None:
        mock_visible = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.none(),
        )
        update_object(user, is_superuser=True)
        client.force_login(user)

        response = client.get(self.path("any"))

        self.assert_response_is_ok(response)
        mock_visible.assert_not_called()

    def test_allows_user_with_matching_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.CHAIR,
        )
        mock_visible = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        mock_visible.assert_awaited_once_with(user)

    def test_forbids_user_without_required_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        mock_visible = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        mock_visible.assert_awaited_once_with(user)


@pytest.mark.django_db
class TestHasAnyConferenceRolesMultiple(ConferenceAuthTestCase):
    auth = has_any_conference_roles(ConferenceRole.CHAIR, ConferenceRole.REVIEWER)

    def test_allows_user_with_any_role(
        self,
        client: Client,
        conference: Conference,
        user: User,
        mocker: MockerFixture,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.REVIEWER,
        )
        mock_visible = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_ok(response)
        mock_visible.assert_awaited_once_with(user)

    def test_forbids_user_without_any_required_roles(
        self,
        client: Client,
        conference: Conference,
        user: User,
        mocker: MockerFixture,
    ) -> None:
        ConferenceRoleAssignment.objects.create(
            conference=conference,
            user=user,
            role=ConferenceRole.SECRETARY,
        )
        mock_visible = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name))

        self.assert_response_is_forbidden(response)
        mock_visible.assert_awaited_once_with(user)


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
        mocker: MockerFixture,
        client: Client,
        user: User,
    ) -> None:
        mock_conference = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.none(),
        )
        mock_tracks = mocker.patch.object(
            ConferenceService,
            "visible_tracks",
            return_value=Track.objects.none(),
        )
        update_object(user, is_superuser=True)
        client.force_login(user)

        response = client.get(self.path("any", "track"))

        self.assert_response_is_ok(response)
        mock_conference.assert_not_called()
        mock_tracks.assert_not_called()

    def test_allows_user_with_matching_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        mock_conference = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        mock_tracks = mocker.patch.object(
            ConferenceService,
            "visible_tracks",
            return_value=Track.objects.filter(pk=track.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_ok(response)
        mock_conference.assert_awaited_once_with(user)
        mock_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_forbids_user_without_required_role(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.SECRETARY,
        )
        mock_conference = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        mock_tracks = mocker.patch.object(
            ConferenceService,
            "visible_tracks",
            return_value=Track.objects.filter(pk=track.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_forbidden(response)
        mock_conference.assert_awaited_once_with(user)
        mock_tracks.assert_awaited_once_with(user, [mocker.ANY])


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
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.REVIEWER,
        )
        mock_conference = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        mock_tracks = mocker.patch.object(
            ConferenceService,
            "visible_tracks",
            return_value=Track.objects.filter(pk=track.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_ok(response)
        mock_conference.assert_awaited_once_with(user)
        mock_tracks.assert_awaited_once_with(user, [mocker.ANY])

    def test_forbids_user_without_any_required_roles(
        self,
        mocker: MockerFixture,
        client: Client,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        TrackRoleAssignment.objects.create(
            track=track,
            user=user,
            role=TrackRole.SECRETARY,
        )
        mock_conference = mocker.patch.object(
            ConferenceService,
            "visible_conferences",
            return_value=Conference.objects.filter(pk=conference.pk),
        )
        mock_tracks = mocker.patch.object(
            ConferenceService,
            "visible_tracks",
            return_value=Track.objects.filter(pk=track.pk),
        )
        client.force_login(user)

        response = client.get(self.path(conference.name, str(track.uid)))

        self.assert_response_is_forbidden(response)
        mock_conference.assert_awaited_once_with(user)
        mock_tracks.assert_awaited_once_with(user, [mocker.ANY])
