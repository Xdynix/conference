from enum import StrEnum
from typing import Literal

from ninja import Field, Schema

from app.utils.enums import Region

RegionCode = StrEnum("RegionCode", {region.name: region.name for region in Region})  # type: ignore[misc]


class Profile(Schema):
    given_name: str = Field("", examples=["John"])
    family_name: str = Field("", examples=["Smith"])
    affiliation: str = Field(
        "",
        examples=["Department of Physics, University of Oxford"],
    )
    region_code: Literal[""] | RegionCode = Field("", examples=[Region.GB.name])
