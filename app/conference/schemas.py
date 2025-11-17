from enum import StrEnum
from typing import Literal

from ninja import Field, Schema

from app.conference.models import Profile as ProfileModel
from app.utils.enums import Region

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
