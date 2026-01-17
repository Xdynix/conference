__all__ = (
    "Affiliation",
    "AttendanceType",
    "AttendanceTypeDisplayName",
    "Conference",
    "ConferenceDisplayName",
    "ConferenceLocation",
    "ConferenceName",
    "ConferenceUser",
    "FamilyName",
    "GivenName",
    "IEEEeCopyrightConfig",
    "IEEEeCopyrightConfigArticleSource",
    "IEEEeCopyrightConfigPublicationTitle",
    "Invitation",
    "InvitationTrackRole",
    "KeywordSetName",
    "KeywordText",
    "Paper",
    "PaperAbstract",
    "PaperAuthor",
    "PaperAuthorPhone",
    "PaperCode",
    "PaperContribution",
    "PaperDetailMixin",
    "PaperFinal",
    "PaperSubmission",
    "PaperTitle",
    "PaperTrack",
    "Payment",
    "PaymentAmount",
    "PaymentItem",
    "PaymentItemAmount",
    "PaymentItemDescription",
    "PaymentNote",
    "PaymentReference",
    "Profile",
    "RegionCode",
    "Registration",
    "RegistrationPaper",
    "RegistrationPhone",
    "RegistrationReceiptTitle",
    "RegistrationSelfIntroduction",
    "Review",
    "ReviewComment",
    "ReviewDetailMixin",
    "ReviewOfflineReviewerName",
    "ReviewPaper",
    "ReviewScore",
    "RoleAssignment",
    "Track",
    "TrackDisplayName",
    "UserConferenceProfile",
)

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from django.utils.translation import gettext as _
from ninja import Field, Schema
from pydantic import (
    AwareDatetime,
    BeforeValidator,
    HttpUrl,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from ulid import ULID

from app.conference.models import AttendanceType as AttendanceTypeModel
from app.conference.models import Conference as ConferenceModel
from app.conference.models import (
    ConferenceRole,
    ConferenceVisibility,
    PaperState,
    PaymentCurrency,
    PaymentMethod,
    PaymentType,
    RegistrationState,
    RegistrationTitle,
    TrackRole,
    TrackVisibility,
)
from app.conference.models import IEEEeCopyrightConfig as IEEEeCopyrightConfigModel
from app.conference.models import Invitation as InvitationModel
from app.conference.models import Keyword as KeywordModel
from app.conference.models import KeywordSet as KeywordSetModel
from app.conference.models import Paper as PaperModel
from app.conference.models import PaperAuthor as PaperAuthorModel
from app.conference.models import Payment as PaymentModel
from app.conference.models import PaymentItem as PaymentItemModel
from app.conference.models import Profile as ProfileModel
from app.conference.models import Registration as RegistrationModel
from app.conference.models import Review as ReviewModel
from app.conference.models import Track as TrackModel
from app.conference.models import UserConferenceProfile as UserConferenceProfileModel
from app.conference.models.review import MAX_SCORE, MIN_SCORE, ReviewState
from app.core.types import EmailStr
from app.utils.enums import Region
from app.utils.sanitization import sanitize_formatted_text, sanitize_text

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
    visibility: TrackVisibility
    submissions_enabled: bool
    accepts_submissions: bool


ieee_ecopyright_config_model_meta = IEEEeCopyrightConfigModel._meta
ieee_ecopyright_config_publication_title_field = (
    ieee_ecopyright_config_model_meta.get_field("publication_title")
)
ieee_ecopyright_config_article_source_field = (
    ieee_ecopyright_config_model_meta.get_field("article_source")
)

IEEEeCopyrightConfigPublicationTitle = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=ieee_ecopyright_config_publication_title_field.max_length,
        strip_whitespace=True,
    ),
]
IEEEeCopyrightConfigArticleSource = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=ieee_ecopyright_config_article_source_field.max_length,
        strip_whitespace=True,
    ),
]


class IEEEeCopyrightConfig(Schema):
    publication_title: IEEEeCopyrightConfigPublicationTitle
    article_source: IEEEeCopyrightConfigArticleSource


conference_meta = ConferenceModel._meta
conference_name_field = conference_meta.get_field("name")
conference_display_name_field = conference_meta.get_field("display_name")
conference_location_field = conference_meta.get_field("location")

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
ConferenceLocation = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=conference_location_field.max_length,
        strip_whitespace=True,
    ),
    Field(
        description=str(conference_location_field.help_text),
        examples=["Cagliari, Italy"],
    ),
]


class Conference(Schema):
    name: ConferenceName
    display_name: ConferenceDisplayName
    visibility: ConferenceVisibility
    registration_enabled: bool
    start_date: date | None = None
    end_date: date | None = None
    location: ConferenceLocation = ""
    tracks: list[Track]
    paper_submission_instructions: str = Field("", max_length=10_000)
    paper_final_instructions: str = Field("", max_length=10_000)

    @field_validator("end_date")
    @classmethod
    def _validate_end_date(cls, v: date | None, info: ValidationInfo) -> date | None:
        start_date = info.data["start_date"]
        if v is None or start_date is None:
            return v
        if v < start_date:
            raise ValueError("End date must be on or after start date.")
        return v


profile_meta = ProfileModel._meta
given_name_field = profile_meta.get_field("given_name")
family_name_field = profile_meta.get_field("family_name")
affiliation_field = profile_meta.get_field("affiliation")

GivenName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=given_name_field.max_length,
        strip_whitespace=True,
    ),
    Field(examples=["John"]),
]
FamilyName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=family_name_field.max_length,
        strip_whitespace=True,
    ),
    Field(examples=["Doe"]),
]
Affiliation = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=affiliation_field.max_length,
        strip_whitespace=True,
    ),
    Field(examples=["Department of Physics, University of Oxford"]),
]
RegionCode = StrEnum("RegionCode", {region.name: region.name for region in Region})  # type: ignore[misc]


class Profile(Schema):
    given_name: GivenName = ""
    family_name: FamilyName = ""
    affiliation: Affiliation = ""
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
    state: InvitationModel.State
    invitee_email: EmailStr
    create_time: AwareDatetime
    update_time: AwareDatetime
    accept_time: AwareDatetime | None
    reject_time: AwareDatetime | None
    last_email_send_time: AwareDatetime | None
    email_send_count: int = Field(ge=0)
    conference_roles: list[ConferenceRole]
    track_roles: list[InvitationTrackRole]


class ConferenceUser(Schema):
    uid: ULID
    email: EmailStr | Literal[""] = Field(title=_("Email Address"))
    profile: Profile | None = None


class RoleAssignmentTrackRole(Schema):
    track: ULID
    role: TrackRole


class RoleAssignment(ConferenceUser):
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
PaperAbstract = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
]
PaperContribution = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
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


class PaperAuthor(Profile):
    email: EmailStr | Literal[""] = Field("", title=_("Email Address"))
    phone: PaperAuthorPhone = ""
    corresponding: bool = False


class PaperSubmission(Schema):
    uid: ULID
    display_name: str = Field(examples=["PAPER-1001.pdf"])
    download_url: HttpUrl


class PaperFinal(Schema):
    uid: ULID
    display_name: str = Field(examples=["PAPER-1001.zip"])
    viewable_display_name: str | None = Field(examples=["PAPER-1001-viewable.pdf"])
    download_url: HttpUrl
    viewable_download_url: HttpUrl | None


class Paper(Schema):
    uid: ULID
    conference: ConferenceName
    track: PaperTrack
    code: PaperCode
    create_time: AwareDatetime
    state: PaperState
    withdraw_time: AwareDatetime | None
    title: PaperTitle
    authors: list[PaperAuthor]
    submission: PaperSubmission | None
    final: PaperFinal | None


class PaperDetailMixin(Schema):
    abstract: PaperAbstract
    contribution: PaperContribution
    keywords: list[KeywordText]


review_meta = ReviewModel._meta
review_offline_reviewer_name_field = review_meta.get_field("offline_reviewer_name")

ReviewOfflineReviewerName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=review_offline_reviewer_name_field.max_length,
        strip_whitespace=True,
    ),
    Field(description=str(review_offline_reviewer_name_field.help_text)),
]
ReviewScore = Annotated[int, Field(ge=MIN_SCORE, le=MAX_SCORE)]
ReviewComment = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
]


class ReviewPaper(Schema):
    uid: ULID
    conference: ConferenceName
    track: PaperTrack
    code: PaperCode
    title: PaperTitle
    submission: PaperSubmission | None


class Review(Schema):
    uid: ULID
    create_time: AwareDatetime
    paper: ReviewPaper
    state: ReviewState
    submit_time: AwareDatetime | None


class ReviewDetailMixin(Schema):
    originality: ReviewScore | None
    significance: ReviewScore | None
    technical: ReviewScore | None
    reference: ReviewScore | None
    presentation: ReviewScore | None
    match_topic: ReviewScore | None
    recommendation: ReviewScore | None
    contribution: ReviewComment
    decision_reason: ReviewComment
    comments: ReviewComment
    confidential_remarks: ReviewComment


attendance_type_meta = AttendanceTypeModel._meta
attendance_type_display_name_field = attendance_type_meta.get_field("display_name")

AttendanceTypeDisplayName = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        min_length=1,
        max_length=attendance_type_display_name_field.max_length,
        strip_whitespace=True,
    ),
]


class AttendanceType(Schema):
    uid: ULID
    display_name: AttendanceTypeDisplayName
    admin_only: bool
    paper_required: bool


registration_meta = RegistrationModel._meta
registration_receipt_title_field = registration_meta.get_field("receipt_title")
registration_phone_field = registration_meta.get_field("phone")

RegistrationReceiptTitle = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=registration_receipt_title_field.max_length,
        strip_whitespace=True,
    ),
]
RegistrationPhone = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=registration_phone_field.max_length,
        strip_whitespace=True,
    ),
]  # TODO: Consider use Pydantic's `PhoneNumber` type.
RegistrationSelfIntroduction = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=1_000),
]


class RegistrationPaper(Schema):
    code: PaperCode
    title: PaperTitle


class Registration(Profile):
    uid: ULID
    create_time: AwareDatetime
    conference: ConferenceName
    reference_code: str
    state: RegistrationState
    paper: RegistrationPaper | None
    attendance_type: AttendanceType
    receipt_title: RegistrationReceiptTitle
    title: RegistrationTitle | Literal[""]
    email: EmailStr | Literal[""] = Field(title=_("Email Address"))
    phone: RegistrationPhone
    self_introduction: RegistrationSelfIntroduction


payment_item_meta = PaymentItemModel._meta
payment_item_amount_field = payment_item_meta.get_field("amount")
payment_item_description_field = payment_item_meta.get_field("description")

PaymentItemAmount = Annotated[
    Decimal,
    Field(
        ge=0,
        max_digits=payment_item_amount_field.max_digits,
        decimal_places=payment_item_amount_field.decimal_places,
        examples=["100.00"],
    ),
]
PaymentItemDescription = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=payment_item_description_field.max_length,
        strip_whitespace=True,
    ),
]


class PaymentItem(Schema):
    amount: PaymentItemAmount
    description: PaymentItemDescription = ""


payment_meta = PaymentModel._meta
payment_amount_field = payment_meta.get_field("amount")
payment_reference_field = payment_meta.get_field("reference")

PaymentAmount = Annotated[
    Decimal,
    Field(
        ge=0,
        max_digits=payment_amount_field.max_digits,
        decimal_places=payment_amount_field.decimal_places,
        examples=["100.00"],
    ),
]
PaymentReference = Annotated[
    str,
    BeforeValidator(sanitize_text),
    StringConstraints(
        max_length=payment_reference_field.max_length,
        strip_whitespace=True,
    ),
]
PaymentNote = Annotated[
    str,
    BeforeValidator(sanitize_formatted_text),
    StringConstraints(max_length=10_000),
]


class Payment(Schema):
    amount: PaymentAmount
    currency: PaymentCurrency
    type: PaymentType
    method: PaymentMethod
    reference: PaymentReference
    note: PaymentNote
