from enum import StrEnum
from typing import Literal

from ninja import Field, Schema
from ulid import ULID

from app.conference.models import Conference as ConferenceModel
from app.conference.models import Profile as ProfileModel
from app.conference.models import Track as TrackModel
from app.utils.enums import Region

conference_meta = ConferenceModel._meta
conference_name_field = conference_meta.get_field("name")
conference_display_name_field = conference_meta.get_field("display_name")


class Conference(Schema):
    name: str = Field(
        description=str(conference_name_field.help_text),
        examples=["CBPK-2020"],
        pattern=r"^[-a-zA-Z0-9_]+$",  # django.core.validators.slug_re
        min_length=1,
        max_length=conference_name_field.max_length,
    )
    display_name: str = Field(
        description=str(conference_display_name_field.help_text),
        min_length=1,
        max_length=conference_display_name_field.max_length,
    )
    visibility: ConferenceModel.Visibility
    tracks: list["Track"] = Field(validation_alias="prefetched_tracks")


track_meta = TrackModel._meta
track_display_name_field = track_meta.get_field("display_name")


class Track(Schema):
    uid: ULID
    display_name: str = Field(
        min_length=1,
        max_length=track_display_name_field.max_length,
    )
    visibility: TrackModel.Visibility


profile_meta = ProfileModel._meta
given_name_field = profile_meta.get_field("given_name")
family_name_field = profile_meta.get_field("family_name")
affiliation_field = profile_meta.get_field("affiliation")

RegionCode = StrEnum("RegionCode", {region.name: region.name for region in Region})  # type: ignore[misc]


class Profile(Schema):
    given_name: str = Field(
        "",
        examples=["John"],
        max_length=given_name_field.max_length,
    )
    family_name: str = Field(
        "",
        examples=["Doe"],
        max_length=family_name_field.max_length,
    )
    affiliation: str = Field(
        "",
        examples=["Department of Physics, University of Oxford"],
        max_length=affiliation_field.max_length,
    )
    region_code: Literal[""] | RegionCode = Field("", examples=[Region.GB.name])
