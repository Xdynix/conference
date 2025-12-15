__all__ = (
    "Conference",
    "ConferenceDisplayName",
    "ConferenceName",
    "Invitation",
    "InvitationTrackRole",
    "KeywordSetName",
    "KeywordText",
    "Paper",
    "PaperAuthor",
    "PaperAuthorPhone",
    "PaperCode",
    "PaperOwner",
    "PaperTitle",
    "PaperTrack",
    "Profile",
    "RoleAssignment",
    "Track",
    "TrackDisplayName",
    "UserConferenceProfile",
)


from enum import StrEnum
from typing import Annotated, Literal

from django.utils.translation import gettext as _
from ninja import Field, Schema
from pydantic import AwareDatetime, BeforeValidator, StringConstraints
from ulid import ULID

from app.conference.models import Conference as ConferenceModel
from app.conference.models import ConferenceRole, TrackRole
from app.conference.models import Invitation as InvitationModel
from app.conference.models import Keyword as KeywordModel
from app.conference.models import KeywordSet as KeywordSetModel
from app.conference.models import Paper as PaperModel
from app.conference.models import PaperAuthor as PaperAuthorModel
from app.conference.models import Profile as ProfileModel
from app.conference.models import Track as TrackModel
from app.conference.models import UserConferenceProfile as UserConferenceProfileModel
from app.core.types import EmailStr, User
from app.utils.enums import Region
from app.utils.sanitization import sanitize_text

KeywordText = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=KeywordModel._meta.get_field("text").max_length,
        strip_whitespace=True,
    ),
]
KeywordSetName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=KeywordSetModel._meta.get_field("name").max_length,
        strip_whitespace=True,
    ),
]


track_meta = TrackModel._meta
track_display_name_field = track_meta.get_field("display_name")

TrackDisplayName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=track_display_name_field.max_length,
        strip_whitespace=True,
    ),
    Field(examples=["Regular"]),
]


class Track(Schema):
    uid: ULID
    display_name: TrackDisplayName
    visibility: TrackModel.Visibility
    accepts_submissions: bool


conference_meta = ConferenceModel._meta
conference_name_field = conference_meta.get_field("name")
conference_display_name_field = conference_meta.get_field("display_name")

ConferenceName = Annotated[
    str,
    StringConstraints(
        pattern=r"^[-a-zA-Z0-9_]+$",  # django.core.validators.slug_re
        min_length=1,
        max_length=conference_name_field.max_length,
    ),
    Field(
        description=str(conference_name_field.help_text),
        examples=["CBPK-2020"],
    ),
]
ConferenceDisplayName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=conference_display_name_field.max_length,
        strip_whitespace=True,
    ),
    Field(
        description=str(conference_display_name_field.help_text),
        examples=["Conference on Blockchain Protocols and Knowledge 2020"],
    ),
]


class Conference(Schema):
    name: ConferenceName
    display_name: ConferenceDisplayName
    visibility: ConferenceModel.Visibility
    tracks: list[Track]


profile_meta = ProfileModel._meta
given_name_field = profile_meta.get_field("given_name")
family_name_field = profile_meta.get_field("family_name")
affiliation_field = profile_meta.get_field("affiliation")

RegionCode = StrEnum("RegionCode", {region.name: region.name for region in Region})  # type: ignore[misc]


class Profile(Schema):
    given_name: Annotated[
        str,
        BeforeValidator(sanitize_text),
        StringConstraints(
            max_length=given_name_field.max_length,
            strip_whitespace=True,
        ),
        Field(examples=["John"]),
    ] = ""
    family_name: Annotated[
        str,
        BeforeValidator(sanitize_text),
        StringConstraints(
            max_length=family_name_field.max_length,
            strip_whitespace=True,
        ),
        Field(examples=["Doe"]),
    ] = ""
    affiliation: Annotated[
        str,
        BeforeValidator(sanitize_text),
        StringConstraints(
            max_length=affiliation_field.max_length,
            strip_whitespace=True,
        ),
        Field(examples=["Department of Physics, University of Oxford"]),
    ] = ""
    region_code: Literal[""] | RegionCode = Field("", examples=[Region.GB.name])


user_conference_profile_meta = UserConferenceProfileModel._meta
desired_paper_count_field = UserConferenceProfileModel._meta.get_field(
    "desired_paper_count"
)


class UserConferenceProfile(Schema):
    desired_paper_count: int = Field(
        description=str(desired_paper_count_field.help_text),
        ge=0,
    )
    interested_keywords: list[KeywordText]


class InvitationTrackRole(Schema):
    track: ULID
    role: TrackRole


class Invitation(UserConferenceProfile, Profile):
    uid: ULID
    status: InvitationModel.Status
    invitee_email: EmailStr
    create_time: AwareDatetime
    update_time: AwareDatetime
    accept_time: AwareDatetime | None
    reject_time: AwareDatetime | None
    last_email_sent_time: AwareDatetime | None
    email_send_count: int = Field(ge=0)
    conference_roles: list[ConferenceRole]
    track_roles: list[InvitationTrackRole]


class RoleAssignmentTrackRole(Schema):
    track: ULID
    role: TrackRole


class RoleAssignment(User):
    profile: Profile | None
    conference_roles: list[ConferenceRole]
    track_roles: list[RoleAssignmentTrackRole]


paper_meta = PaperModel._meta
paper_code_field = paper_meta.get_field("code")
paper_title_field = paper_meta.get_field("title")
paper_author_meta = PaperAuthorModel._meta
paper_author_phone_field = paper_author_meta.get_field("phone")

PaperCode = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=paper_code_field.max_length,
        strip_whitespace=True,
    ),
    Field(examples=["PAPER-1001"]),
]
PaperTitle = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=paper_title_field.max_length,
        strip_whitespace=True,
    ),
]
PaperAuthorPhone = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=paper_author_phone_field.max_length,
        strip_whitespace=True,
    ),
]  # TODO: Consider use Pydantic's `PhoneNumber` type.


# Embeds track data rather than just ULID so the paper remains displayable even if moved
# to a track the author cannot access. This intentionally reveals minimal track info (
# UID and name) regardless of track visibility.
class PaperTrack(Schema):
    uid: ULID
    display_name: TrackDisplayName


class PaperOwner(Schema):
    uid: ULID
    email: EmailStr | Literal[""] = Field(title=_("Email Address"))
    profile: Profile | None


class PaperAuthor(Profile):
    email: EmailStr | Literal[""] = Field(title=_("Email Address"))
    phone: PaperAuthorPhone
    corresponding: bool


class Paper(Schema):
    uid: ULID
    conference: ConferenceName
    track: PaperTrack
    code: PaperCode
    create_time: AwareDatetime
    state: PaperModel.State
    withdrawn_time: AwareDatetime | None
    title: PaperTitle
    authors: list[PaperAuthor]
