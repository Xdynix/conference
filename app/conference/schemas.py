from ninja import Field, Schema

from app.utils.enums import Region


class Profile(Schema):
    given_name: str = Field(examples=["John"])
    family_name: str = Field(examples=["Smith"])
    affiliation: str = Field(examples=["Department of Physics, University of Oxford"])
    region_code: str = Field(examples=[Region.US.name])
