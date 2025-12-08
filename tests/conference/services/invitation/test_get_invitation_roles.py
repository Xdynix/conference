import pytest
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    Invitation,
    Track,
    TrackRole,
)
from app.conference.services import InvitationService

from .conftest import add_invitation_roles


@pytest.mark.django_db
class TestInvitationServiceGetInvitationRoles:
    def test_no_roles(self, invitation: Invitation) -> None:
        conference_roles, track_roles = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == []
        assert track_roles == {}

    def test_conference_roles_only(self, invitation: Invitation) -> None:
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.CHAIR, ConferenceRole.REVIEWER],
        )

        conference_roles, track_roles = InvitationService.get_invitation_roles(
            invitation
        )

        assert set(conference_roles) == {ConferenceRole.CHAIR, ConferenceRole.REVIEWER}
        assert track_roles == {}

    def test_track_roles_only(self, invitation: Invitation, track: Track) -> None:
        add_invitation_roles(
            invitation,
            track_roles={track: [TrackRole.CHAIR, TrackRole.REVIEWER]},
        )

        conference_roles, track_roles_result = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == []
        assert set(track_roles_result) == {track}
        assert set(track_roles_result[track]) == {
            TrackRole.CHAIR,
            TrackRole.REVIEWER,
        }

    def test_mixed_conference_and_track_roles(
        self,
        faker: Faker,
        invitation: Invitation,
        conference: Conference,
        track: Track,
    ) -> None:
        track_b = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        add_invitation_roles(
            invitation,
            conference_roles=[ConferenceRole.SECRETARY],
            track_roles={
                track: [TrackRole.CHAIR, TrackRole.REVIEWER],
                track_b: [TrackRole.SECRETARY],
            },
        )

        conference_roles, track_roles_result = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == [ConferenceRole.SECRETARY]
        assert set(track_roles_result) == {track, track_b}
        assert set(track_roles_result[track]) == {
            TrackRole.CHAIR,
            TrackRole.REVIEWER,
        }
        assert track_roles_result[track_b] == [TrackRole.SECRETARY]

    def test_multiple_tracks_with_roles(
        self,
        faker: Faker,
        invitation: Invitation,
        conference: Conference,
        track: Track,
    ) -> None:
        track_b = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        track_c = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
        )
        add_invitation_roles(
            invitation,
            track_roles={
                track: [TrackRole.CHAIR],
                track_b: [TrackRole.REVIEWER],
                track_c: [TrackRole.SECRETARY],
            },
        )

        conference_roles, track_roles_result = InvitationService.get_invitation_roles(
            invitation
        )

        assert conference_roles == []
        assert set(track_roles_result) == {track, track_b, track_c}
        assert track_roles_result[track] == [TrackRole.CHAIR]
        assert track_roles_result[track_b] == [TrackRole.REVIEWER]
        assert track_roles_result[track_c] == [TrackRole.SECRETARY]

    def test_inactive_tracks_filtered_out(
        self,
        faker: Faker,
        invitation: Invitation,
        conference: Conference,
        track: Track,
    ) -> None:
        inactive_track = Track.objects.create(
            conference=conference,
            display_name=faker.word(),
            active=False,
        )
        add_invitation_roles(
            invitation,
            track_roles={
                track: [TrackRole.CHAIR],
                inactive_track: [TrackRole.SECRETARY],
            },
        )

        _, track_roles_result = InvitationService.get_invitation_roles(invitation)

        assert inactive_track not in track_roles_result
