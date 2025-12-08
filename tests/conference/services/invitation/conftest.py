from collections.abc import Iterable, Mapping

import pytest
from faker import Faker

from app.conference.models import (
    Conference,
    ConferenceRole,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Track,
    TrackRole,
)
from app.core.models import User


def add_invitation_roles(
    invitation: Invitation,
    *,
    conference_roles: Iterable[ConferenceRole] = (),
    track_roles: Mapping[Track, Iterable[TrackRole]] | None = None,
) -> None:
    for conference_role in conference_roles:
        InvitationConferenceRoleEntry.objects.create(
            invitation=invitation,
            role=conference_role,
        )
    for track, roles in (track_roles or {}).items():
        for track_role in roles:
            InvitationTrackRoleEntry.objects.create(
                invitation=invitation,
                track=track,
                role=track_role,
            )


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def inviter(faker: Faker) -> User:
    return User.objects.create_user(username=faker.user_name())


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def track(faker: Faker, conference: Conference) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def invitation(
    faker: Faker,
    conference: Conference,
) -> Invitation:
    return Invitation.objects.create(
        conference=conference,
        invitee_email=faker.email(),
    )
