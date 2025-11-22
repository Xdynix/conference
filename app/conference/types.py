__all__ = (
    "Conference",
    "ConferenceDisplayName",
    "ConferenceName",
    "KeywordSetName",
    "KeywordText",
    "Profile",
    "Track",
    "TrackDisplayName",
    "UserConferenceProfile",
)


from enum import StrEnum
from typing import Annotated, Literal

from ninja import Field, Schema
from pydantic import StringConstraints
from ulid import ULID

from app.conference.models import Conference as ConferenceModel
from app.conference.models import Keyword as KeywordModel
from app.conference.models import KeywordSet as KeywordSetModel
from app.conference.models import Profile as ProfileModel
from app.conference.models import Track as TrackModel
from app.conference.models import UserConferenceProfile as UserConferenceProfileModel
from app.utils.enums import Region

KeywordText = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=KeywordModel._meta.get_field("text").max_length,
        strip_whitespace=True,
    ),
]
KeywordSetName = Annotated[
    str,
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
        StringConstraints(
            max_length=given_name_field.max_length,
            strip_whitespace=True,
        ),
        Field(examples=["John"]),
    ] = ""
    family_name: Annotated[
        str,
        StringConstraints(
            max_length=family_name_field.max_length,
            strip_whitespace=True,
        ),
        Field(examples=["Doe"]),
    ] = ""
    affiliation: Annotated[
        str,
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
