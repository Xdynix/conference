# ruff: noqa: S311

"""Populate the database with realistic staging data.

Requires the 'faker' package (test dependency). Run with:
    uv run --group test manage.py runscript seed-staging

This script flushes the database and cleans the media directory before seeding.
It is NOT idempotent; run on a fresh or expendable database only.
"""

import datetime
import random
import shutil
from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from faker import Faker
from loguru import logger

from app.conference.api.paper.acceptance_letter import _resolve_and_compile_letter
from app.conference.api.registration.receipt import _resolve_and_compile_receipt
from app.conference.models import (
    AcceptanceLetter,
    AdminComment,
    AttendanceType,
    CodePool,
    Conference,
    ConferenceFile,
    ConferenceRole,
    ConferenceRoleAssignment,
    ConferenceVisibility,
    DuplicateAcknowledgment,
    DuplicateMatch,
    DuplicateMatchType,
    DuplicateReport,
    DuplicateReportState,
    EmailSendLog,
    IEEEeCopyrightConfig,
    IEEEeCopyrightConsent,
    Keyword,
    KeywordSet,
    Paper,
    PaperState,
    Payment,
    PaymentCurrency,
    PaymentMethod,
    PaymentType,
    Profile,
    Receipt,
    Registration,
    RegistrationState,
    RegistrationTitle,
    Review,
    ReviewAssignmentLevel,
    ReviewerNotificationLog,
    ReviewState,
    Track,
    TrackRole,
    TrackRoleAssignment,
    TrackVisibility,
    UserConferenceProfile,
)
from app.conference.services.invitation import InvitationService
from app.conference.services.paper import AuthorData, PaperService
from app.conference.services.payment import PaymentItemData, PaymentService
from app.conference.services.registration import RegistrationService
from app.conference.services.review import ReviewService
from app.conference.services.revision import RevisionService
from app.core.models import GlobalRole, GlobalRoleAssignment, User
from app.utils.typst import compile_template

logger = logger.opt(colors=True, depth=1)

# ── Configuration ─────────────────────────────────────────────────────────────

SEED = 42
PASSWORD_HASH = make_password("password")
NUM_USERS = 300
TEST_DATA_DIR = Path(__file__).parent.parent / "tests" / "data"

ACADEMIC_REGIONS: list[tuple[str, int]] = [
    ("US", 20),
    ("CN", 18),
    ("JP", 10),
    ("KR", 8),
    ("IN", 7),
    ("DE", 6),
    ("GB", 5),
    ("FR", 4),
    ("IT", 3),
    ("CA", 3),
    ("AU", 3),
    ("BR", 2),
    ("TW", 2),
    ("SG", 2),
    ("NL", 2),
    ("CH", 1),
    ("SE", 1),
    ("IL", 1),
    ("ES", 1),
    ("AT", 1),
]

UNIVERSITIES = [
    "MIT",
    "Stanford University",
    "Carnegie Mellon University",
    "UC Berkeley",
    "University of Cambridge",
    "ETH Zurich",
    "Tsinghua University",
    "University of Tokyo",
    "KAIST",
    "National University of Singapore",
    "University of Oxford",
    "Max Planck Institute",
    "EPFL",
    "University of Toronto",
    "Peking University",
    "Technical University of Munich",
    "Seoul National University",
    "Indian Institute of Technology",
    "University of Melbourne",
    "Georgia Tech",
    "University of Michigan",
    "Columbia University",
    "NYU",
    "University of Washington",
    "University of Illinois",
    "Zhejiang University",
    "RWTH Aachen University",
    "Delft University of Technology",
    "Kyoto University",
]

KEYWORD_TEXTS = [
    "Machine Learning",
    "Deep Learning",
    "Natural Language Processing",
    "Computer Vision",
    "Reinforcement Learning",
    "Neural Networks",
    "Data Mining",
    "Generative Models",
    "Transfer Learning",
    "Optimization",
    "Bayesian Methods",
    "Graph Learning",
    "Representation Learning",
    "Multi-Task Learning",
    "Federated Learning",
    "Explainable AI",
    "Robotics",
    "Signal Processing",
    "Information Retrieval",
    "Recommender Systems",
    "Speech Processing",
    "Adversarial Learning",
    "Self-Supervised Learning",
    "Meta-Learning",
    "Causal Inference",
    "Time Series Analysis",
    "Privacy & Security",
    "Fairness & Bias",
    "Knowledge Graphs",
    "Quantum Computing",
]

TITLE_PATTERNS = [
    "{adj} {method} for {task}",
    "A {adj} Approach to {task} Using {method}",
    "{method}-Based {task}: A {adj} Framework",
    "Towards {adj} {task} with {method}",
    "On the {adj} Properties of {method} in {task}",
    "{task} via {adj} {method}",
    "Learning {adj} Representations for {task}",
]

ADJECTIVES = [
    "Novel",
    "Efficient",
    "Robust",
    "Scalable",
    "Adaptive",
    "Unified",
    "Hierarchical",
    "Multi-Scale",
    "Lightweight",
    "End-to-End",
    "Self-Supervised",
    "Federated",
    "Differentiable",
    "Interpretable",
    "Compositional",
    "Generalizable",
    "Sample-Efficient",
]

METHODS = [
    "Transformer",
    "Graph Neural Network",
    "Diffusion Model",
    "Variational Autoencoder",
    "Contrastive Learning",
    "Attention Mechanism",
    "Flow Network",
    "Mixture of Experts",
    "Neural ODE",
    "Normalizing Flow",
    "Energy-Based Model",
    "Meta-Learning",
    "Prompt Tuning",
    "Knowledge Distillation",
]

TASKS = [
    "Image Classification",
    "Object Detection",
    "Text Generation",
    "Speech Recognition",
    "Semantic Segmentation",
    "Machine Translation",
    "Anomaly Detection",
    "Time Series Forecasting",
    "Drug Discovery",
    "Protein Folding",
    "Code Generation",
    "Visual Question Answering",
    "Scene Understanding",
    "Point Cloud Processing",
    "Motion Planning",
]

ACCEPTED_STATES = {PaperState.ACCEPTED, PaperState.ACCEPTED_REVISION_NEEDED}
DECIDED_STATES = set(PaperState.decided())
REVIEWABLE_STATES = {
    PaperState.SUBMITTED,
    PaperState.UNDER_REVIEW,
    *DECIDED_STATES,
}

# ── Document Templates ────────────────────────────────────────────────────────

ACCEPTANCE_LETTER_TEMPLATE = """\
#let data = json(bytes(sys.inputs.at("data")))
#set page(margin: (top: 3cm, bottom: 2.5cm, left: 2.5cm, right: 2.5cm))
#set text(size: 11pt, font: "New Computer Modern")

#align(center)[
  #text(size: 16pt, weight: "bold")[#data.conference.display_name]
  #v(0.3em)
  #text(size: 12pt, fill: rgb("#555"))[#data.conference.location]
  #v(1.5em)
  #text(size: 14pt, weight: "bold")[Letter of Acceptance]
]

#v(2em)
Dear #data.paper.user.given_name #data.paper.user.family_name,

#v(0.5em)
We are pleased to inform you that your paper has been *accepted* for
presentation at *#data.conference.display_name*.

#v(0.5em)
*Paper Code:* #data.paper.code \\
*Title:* #data.paper.title \\
*Track:* #data.track.display_name

#v(0.5em)
Please prepare the camera-ready version following the conference guidelines.

#v(2em)
Sincerely, \\
The Organizing Committee
"""

RECEIPT_TEMPLATE = """\
#let data = json(bytes(sys.inputs.at("data")))
#set page(margin: (top: 3cm, bottom: 2.5cm, left: 2.5cm, right: 2.5cm))
#set text(size: 10pt, font: "New Computer Modern")

#align(center)[
  #text(size: 16pt, weight: "bold")[#data.conference.display_name]
  #v(0.3em)
  #text(size: 12pt)[Registration Receipt]
]

#v(2em)
*Registration Details* \\
Reference: #data.registration.reference_code \\
Name: #data.registration.given_name #data.registration.family_name \\
Affiliation: #data.registration.affiliation \\
Type: #data.registration.attendance_type.display_name

#v(1em)
Issued on behalf of the organizing committee.
"""

SEED_PDF_TEMPLATE = """\
#let data = json(bytes(sys.inputs.at("data")))
#set page(margin: 2.5cm)
#set text(size: 11pt)

= #data.heading

This is generated staging content for #data.paper_code.

Conference: #data.conference_name \\
Revision: #data.revision
"""

# ── Conference Specifications ─────────────────────────────────────────────────

CONFERENCE_SPECS: list[dict[str, Any]] = [
    {
        "name": "ICML-2026",
        "display_name": "International Conference on Machine Learning 2026",
        "visibility": ConferenceVisibility.PUBLIC,
        "registration_enabled": True,
        "location": "Tokyo, Japan",
        "start_delta_days": 90,
        "duration_days": 4,
        "code_prefix": "ML-",
        "num_papers": 200,
        "currency": PaymentCurrency.JPY,
        "payment_amount_range": (30000, 80000),
        "ieee_ecopyright": True,
        "tracks": [
            "Supervised Learning",
            "Unsupervised Learning & Generative Models",
            "Reinforcement Learning & Planning",
            "Applications & Social Impact",
        ],
        "track_weights": [35, 30, 20, 15],
        "state_weights": {
            PaperState.DRAFT: 10,
            PaperState.SUBMITTED: 25,
            PaperState.UNDER_REVIEW: 20,
            PaperState.ACCEPTED: 25,
            PaperState.REJECTED: 15,
            PaperState.ACCEPTED_REVISION_NEEDED: 5,
        },
    },
    {
        "name": "CVPR-2026",
        "display_name": "Computer Vision and Pattern Recognition 2026",
        "visibility": ConferenceVisibility.MEMBER_ONLY,
        "registration_enabled": True,
        "location": "Barcelona, Spain",
        "start_delta_days": 120,
        "duration_days": 3,
        "code_prefix": "CV-",
        "num_papers": 120,
        "currency": PaymentCurrency.EUR,
        "payment_amount_range": (300, 800),
        "ieee_ecopyright": False,
        "tracks": [
            "Image Recognition & Detection",
            "Video Analysis & Tracking",
            "3D Vision & Reconstruction",
        ],
        "track_weights": [40, 35, 25],
        "state_weights": {
            PaperState.DRAFT: 12,
            PaperState.SUBMITTED: 28,
            PaperState.UNDER_REVIEW: 22,
            PaperState.ACCEPTED: 20,
            PaperState.REJECTED: 13,
            PaperState.ACCEPTED_REVISION_NEEDED: 5,
        },
    },
    {
        "name": "NIPS-2025",
        "display_name": "Neural Information Processing Systems 2025",
        "visibility": ConferenceVisibility.ADMIN_ONLY,
        "registration_enabled": False,
        "location": "Vancouver, Canada",
        "start_delta_days": -30,
        "duration_days": 5,
        "code_prefix": "NP-",
        "num_papers": 80,
        "currency": PaymentCurrency.USD,
        "payment_amount_range": (400, 900),
        "ieee_ecopyright": False,
        "tracks": [
            "Theory & Foundations",
            "Applications",
        ],
        "track_weights": [55, 45],
        "state_weights": {
            PaperState.DRAFT: 2,
            PaperState.SUBMITTED: 3,
            PaperState.UNDER_REVIEW: 5,
            PaperState.ACCEPTED: 50,
            PaperState.REJECTED: 32,
            PaperState.ACCEPTED_REVISION_NEEDED: 8,
        },
    },
]


# ── Paper Plan ────────────────────────────────────────────────────────────────


@dataclass
class PaperPlan:
    """Pre-determined lifecycle plan for a single paper."""

    owner: User
    track: Track
    target_state: str
    withdrawn: bool = False
    soft_deleted: bool = False
    announced: bool = False
    paper: Paper = field(init=False)


# ── Utilities ─────────────────────────────────────────────────────────────────


def _pick_region() -> str:
    codes, weights = zip(*ACADEMIC_REGIONS, strict=False)
    return cast(str, random.choices(codes, weights=weights, k=1)[0])


def _weighted(options: dict[Any, int]) -> Any:
    keys = list(options.keys())
    weights = list(options.values())
    return random.choices(keys, weights=weights, k=1)[0]


def _generate_title() -> str:
    pattern = random.choice(TITLE_PATTERNS)
    return pattern.format(
        adj=random.choice(ADJECTIVES),
        method=random.choice(METHODS),
        task=random.choice(TASKS),
    )


def _create_pdf_bytes(paper: Paper, revision: int, heading: str) -> bytes:
    return compile_template(
        SEED_PDF_TEMPLATE,
        {
            "heading": heading,
            "paper_code": paper.code,
            "conference_name": paper.track.conference.name,
            "revision": revision,
        },
    )


def _create_docx_bytes(
    template: bytes,
    paper: Paper,
    revision: int,
    document_type: str,
) -> bytes:
    identifier = escape(
        f"{document_type} for {paper.track.conference.name}/{paper.code}, "
        f"revision {revision}."
    )
    paragraph = f"<w:p><w:r><w:t>{identifier}</w:t></w:r></w:p>".encode()
    output = BytesIO()

    with ZipFile(BytesIO(template)) as source, ZipFile(output, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "word/document.xml":
                marker = b"<w:sectPr"
                marker_index = content.index(marker)
                content = content[:marker_index] + paragraph + content[marker_index:]
            target.writestr(info, content)

    return output.getvalue()


def _create_zip_bytes(paper: Paper, revision: int) -> bytes:
    content = (
        f"= Final source for {paper.code}\n\n"
        f"Conference: {paper.track.conference.name}\\\n"
        f"Revision: {revision}\n"
    ).encode()
    output = BytesIO()
    info = ZipInfo("main.typ", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16

    with ZipFile(output, "w") as archive:
        archive.writestr(info, content)

    return output.getvalue()


def _past_time(min_days: int = 1, max_days: int = 60) -> datetime.datetime:
    return timezone.now() - datetime.timedelta(
        days=random.randint(min_days, max_days),
        hours=random.randint(0, 23),
    )


# ── Entry Point ───────────────────────────────────────────────────────────────


def run() -> None:
    Faker.seed(SEED)
    random.seed(SEED)
    fake = Faker()

    logger.info("Flushing database and cleaning media...")
    _flush_and_clean()

    logger.info("Seeding users...")
    users, profiles = _seed_users(fake)

    logger.info("Seeding keywords...")
    keywords = _seed_keywords()

    for spec in CONFERENCE_SPECS:
        logger.info(f"Seeding conference: <green>{spec['name']}</>")
        _seed_conference(fake, users, profiles, keywords, spec)

    logger.info("<green>Staging seed complete.</>")


# ── Database Reset ────────────────────────────────────────────────────────────


def _flush_and_clean() -> None:
    call_command("flush", "--no-input", verbosity=0)
    media_root = settings.MEDIA_ROOT
    if media_root.is_dir():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True, exist_ok=True)


# ── Users ─────────────────────────────────────────────────────────────────────


def _seed_users(
    fake: Faker,
) -> tuple[list[User], dict[int, dict[str, str]]]:
    """Create all users and profiles.

    Returns:
        A tuple of (user_list, profiles_dict) where profiles_dict maps
        user.pk to profile field values.
    """
    user_objects: list[User] = []
    profile_specs: list[tuple[str, str, str, str]] = []

    # Superuser
    user_objects.append(
        User(
            username="superuser",
            email="superuser@example.com",
            password=PASSWORD_HASH,
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
    )
    profile_specs.append(("Super", "User", "System", "US"))

    # Global admin
    user_objects.append(
        User(
            username="global-admin",
            email="global-admin@example.com",
            password=PASSWORD_HASH,
            is_active=True,
        )
    )
    profile_specs.append(("Global", "Admin", "Admin Organization", "US"))

    # Regular users
    for i in range(NUM_USERS - 2):
        user_objects.append(
            User(
                username=f"user-{i:03d}",
                email=f"user-{i:03d}@example.com",
                password=PASSWORD_HASH,
                is_active=True,
            )
        )
        profile_specs.append(
            (
                fake.first_name(),
                fake.last_name(),
                random.choice(UNIVERSITIES),
                _pick_region(),
            )
        )

    User.objects.bulk_create(user_objects)

    profiles_dict: dict[int, dict[str, str]] = {}
    profile_objects: list[Profile] = []
    for user, (given, family, affil, region) in zip(
        user_objects,
        profile_specs,
        strict=True,
    ):
        profiles_dict[user.pk] = {
            "given_name": given,
            "family_name": family,
            "affiliation": affil,
            "region_code": region,
        }
        profile_objects.append(
            Profile(
                user=user,
                given_name=given,
                family_name=family,
                affiliation=affil,
                region_code=region,
            )
        )
    Profile.objects.bulk_create(profile_objects)

    admin = next(u for u in user_objects if u.username == "global-admin")
    GlobalRoleAssignment.objects.create(user=admin, role=GlobalRole.ADMIN)

    logger.info(f"    Created <green>{len(user_objects)}</> users")
    regular = [
        u for u in user_objects if not u.is_superuser and u.username != "global-admin"
    ]
    return regular, profiles_dict


# ── Keywords ──────────────────────────────────────────────────────────────────


def _seed_keywords() -> list[Keyword]:
    kw_objects = [Keyword(text=text) for text in KEYWORD_TEXTS]
    Keyword.objects.bulk_create(kw_objects)

    # Create a couple of keyword sets for reuse
    set1 = KeywordSet.objects.create(name="AI & ML Core")
    set1.keywords.set(kw_objects[:10])
    set2 = KeywordSet.objects.create(name="Applied AI")
    set2.keywords.set(kw_objects[10:20])

    logger.info(f"    Created <green>{len(kw_objects)}</> keywords, 2 keyword sets")
    return kw_objects


# ── Conference Orchestrator ───────────────────────────────────────────────────


def _seed_conference(
    fake: Faker,
    users: list[User],
    profiles: dict[int, dict[str, str]],
    keywords: list[Keyword],
    spec: dict[str, Any],
) -> None:
    today = datetime.date.today()
    is_past = spec["start_delta_days"] < 0

    # 1. Conference structure.
    conference = Conference.objects.create(
        name=spec["name"],
        display_name=spec["display_name"],
        active=True,
        visibility=spec["visibility"],
        registration_enabled=spec["registration_enabled"],
        location=spec["location"],
        start_date=today + datetime.timedelta(days=spec["start_delta_days"]),
        end_date=today
        + datetime.timedelta(
            days=spec["start_delta_days"] + spec["duration_days"],
        ),
        paper_submission_instructions=(
            "## Submission Guidelines\n\n"
            "Please submit your paper in **PDF format**.\n\n"
            "- Maximum 10 pages (excluding references)\n"
            "- Double-blind review: remove author names\n"
        ),
        paper_final_instructions=(
            "## Camera-Ready Guidelines\n\n"
            "1. Include author names and affiliations\n"
            "2. Address all reviewer comments\n"
            "3. Submit source files and final PDF\n"
        ),
    )
    conference.keywords.set(random.sample(keywords, k=min(8, len(keywords))))

    code_pool = CodePool.objects.create(
        conference=conference,
        name="Main Pool",
        prefix=spec["code_prefix"],
    )

    tracks: list[Track] = []
    for i, track_name in enumerate(spec["tracks"]):
        tracks.append(
            Track(
                conference=conference,
                code_pool=code_pool,
                display_name=track_name,
                active=True,
                ordering=i,
                visibility=TrackVisibility.PUBLIC,
                submissions_enabled=not is_past,
            )
        )
    Track.objects.bulk_create(tracks)

    att_types = _create_attendance_types(conference)

    # 2. Roles
    admins, reviewers = _assign_roles(users, conference, tracks)

    # 3. Plan papers (determine target states and lifecycle flags)
    plans = _plan_papers(users, tracks, spec, is_past)

    # 3b. Ensure paper owners have at least MEMBER role (needed for MEMBER_ONLY
    # visibility)
    _ensure_owner_membership(plans, conference)

    # 4. Create draft papers via PaperService (proper code pool allocation)
    _create_draft_papers(fake, profiles, keywords, plans)

    # 5. Upload submission files for papers that will be submitted
    _upload_submissions(plans)

    # 6. Submit papers (DRAFT -> SUBMITTED)
    _submit_papers(plans)

    # 7. Withdraw papers (must happen before review assignment)
    _withdraw_papers(plans)

    # 8. Assign reviewers and process review lifecycle (SUBMITTED -> UNDER_REVIEW)
    _create_reviews(fake, plans, reviewers, admins, conference, keywords)

    # 9. Decide papers
    _decide_papers(plans, admins)

    # 10. Create acceptance letters for decided papers that will be announced
    _create_acceptance_letters(conference, plans)

    # 11. Announce papers (set announce_time after letters exist)
    _announce_papers(conference, plans)

    # 12. Create finals for announced accepted papers
    _create_finals(plans)

    # 13. Soft-delete papers
    _soft_delete_papers(plans)

    # 14. Refresh paper objects from DB after all state mutations so downstream
    #     code sees current state, delete_time, announce_time, etc.
    _refresh_papers(plans)

    # 15. Registrations
    papers = [plan.paper for plan in plans]
    registrations = _create_registrations(
        fake,
        users,
        profiles,
        conference,
        papers,
        att_types,
    )

    # 17. Payments
    _create_payments(conference, registrations, spec)

    # 18. Invitations
    _create_invitations(fake, users, admins, conference, tracks, keywords)

    # 19. Documents (receipts, conference files; letters already created above)
    _create_documents(conference, registrations)

    # 20. Email send logs
    _create_email_logs(admins, conference)

    # 21. Duplicate detection data
    _create_duplicate_data(papers, admins, conference)

    # 22. IEEE eCopyright (main conference only)
    if spec.get("ieee_ecopyright"):
        _create_ieee_ecopyright(conference, tracks, papers)

    logger.info(f"    <green>{spec['name']}</> complete")


# ── Attendance Types ──────────────────────────────────────────────────────────


def _create_attendance_types(conference: Conference) -> dict[str, AttendanceType]:
    specs = [
        ("Author", False, True),
        ("Regular Attendee", False, False),
        ("Student", False, False),
        ("VIP", True, False),
    ]
    types: dict[str, AttendanceType] = {}
    for i, (name, admin_only, paper_required) in enumerate(specs):
        types[name] = AttendanceType.objects.create(
            conference=conference,
            display_name=name,
            ordering=i,
            admin_only=admin_only,
            paper_required=paper_required,
        )
    return types


# ── Roles ─────────────────────────────────────────────────────────────────────


def _assign_roles(
    users: list[User],
    conference: Conference,
    tracks: list[Track],
) -> tuple[list[User], list[User]]:
    """Assign conference and track roles. Returns (admins, reviewers)."""
    pool = list(users)
    random.shuffle(pool)

    # Conference-level: 1 chair, 2 secretaries, ~20 reviewers, ~5 members
    chair = pool[0]
    secretaries = pool[1:3]
    conf_reviewers = pool[3:23]
    members = pool[23:28]

    conf_role_objs: list[ConferenceRoleAssignment] = []
    conf_role_objs.append(
        ConferenceRoleAssignment(
            conference=conference,
            user=chair,
            role=ConferenceRole.CHAIR,
        )
    )
    for u in secretaries:
        conf_role_objs.append(
            ConferenceRoleAssignment(
                conference=conference,
                user=u,
                role=ConferenceRole.SECRETARY,
            )
        )
    for u in conf_reviewers:
        conf_role_objs.append(
            ConferenceRoleAssignment(
                conference=conference,
                user=u,
                role=ConferenceRole.REVIEWER,
            )
        )
    for u in members:
        conf_role_objs.append(
            ConferenceRoleAssignment(
                conference=conference,
                user=u,
                role=ConferenceRole.MEMBER,
            )
        )
    ConferenceRoleAssignment.objects.bulk_create(conf_role_objs)

    # Track-level: 1 chair + 2-4 reviewers per track (no user reuse within a track)
    track_role_objs: list[TrackRoleAssignment] = []
    track_reviewer_pool = list(pool[28:60])
    random.shuffle(track_reviewer_pool)
    cursor = 0
    for track in tracks:
        needed = 1 + random.randint(2, 4)  # 1 chair + N reviewers
        # Wrap around if pool exhausted
        assigned: list[User] = []
        while len(assigned) < needed:
            assigned.append(track_reviewer_pool[cursor % len(track_reviewer_pool)])
            cursor += 1
        track_role_objs.append(
            TrackRoleAssignment(
                track=track,
                user=assigned[0],
                role=TrackRole.CHAIR,
            )
        )
        for u in assigned[1:]:
            track_role_objs.append(
                TrackRoleAssignment(
                    track=track,
                    user=u,
                    role=TrackRole.REVIEWER,
                )
            )
    TrackRoleAssignment.objects.bulk_create(track_role_objs)

    admins = [chair, *secretaries]
    all_reviewers = list(conf_reviewers)
    logger.info(
        f"    Assigned <green>{len(conf_role_objs)}</> conference roles, "
        f"<green>{len(track_role_objs)}</> track roles",
    )
    return admins, all_reviewers


# ── Paper Planning ────────────────────────────────────────────────────────────


def _plan_papers(
    users: list[User],
    tracks: list[Track],
    spec: dict[str, Any],
    is_past: bool,
) -> list[PaperPlan]:
    """Pre-determine the lifecycle plan for each paper."""
    num_papers = spec["num_papers"]
    state_weights = spec["state_weights"]
    track_weights = spec["track_weights"]

    # Owners: power-law distribution (most get 1 paper, few get many)
    author_pool = list(users)
    random.shuffle(author_pool)
    owner_weights = [1.0 / (i / 5 + 1) for i in range(len(author_pool))]
    owners = random.choices(author_pool, weights=owner_weights, k=num_papers)

    paper_tracks = random.choices(tracks, weights=track_weights, k=num_papers)
    paper_states = [_weighted(state_weights) for _ in range(num_papers)]

    plans: list[PaperPlan] = []
    for seq in range(num_papers):
        state = paper_states[seq]
        is_draft = state == PaperState.DRAFT
        is_decided = state in DECIDED_STATES

        withdrawn = not is_draft and not is_decided and random.random() < 0.05
        # Mutually exclusive: delete_paper raises PaperWithdrawnError on
        # withdrawn papers.
        soft_deleted = not withdrawn and random.random() < 0.02
        announced = is_decided and (is_past or random.random() < 0.8)

        plans.append(
            PaperPlan(
                owner=owners[seq],
                track=paper_tracks[seq],
                target_state=state,
                withdrawn=withdrawn,
                soft_deleted=soft_deleted,
                announced=announced,
            )
        )

    return plans


# ── Owner Membership ─────────────────────────────────────────────────────────


def _ensure_owner_membership(
    plans: list[PaperPlan],
    conference: Conference,
) -> None:
    """Assign MEMBER role to paper owners who don't already have a conference role.

    Only needed for MEMBER_ONLY conferences where users without a role cannot
    access their own papers.
    """
    if conference.visibility != ConferenceVisibility.MEMBER_ONLY:
        return

    seen: set[int] = set()
    count = 0
    for plan in plans:
        pk = plan.owner.pk
        if pk in seen:
            continue
        seen.add(pk)
        _, created = ConferenceRoleAssignment.objects.get_or_create(
            conference=conference,
            user=plan.owner,
            defaults={"role": ConferenceRole.MEMBER},
        )
        if created:
            count += 1

    if count:
        logger.info(f"    Assigned MEMBER role to <green>{count}</> paper owners")


# ── Paper Creation (via PaperService) ─────────────────────────────────────────


def _create_draft_papers(
    fake: Faker,
    profiles: dict[int, dict[str, str]],
    keywords: list[Keyword],
    plans: list[PaperPlan],
) -> None:
    """Create all papers as DRAFT via PaperService for correct code pool allocation."""
    for plan in plans:
        owner = plan.owner
        p = profiles.get(owner.pk, {})

        # Build author list (1-4 per paper, first is owner)
        num_authors = random.choices([1, 2, 3, 4], weights=[15, 40, 30, 15])[0]
        authors: list[AuthorData] = [
            AuthorData(
                given_name=p.get("given_name", "Unknown"),
                family_name=p.get("family_name", "Author"),
                email=owner.email,
                affiliation=p.get("affiliation", ""),
                region_code=p.get("region_code", ""),
                corresponding=True,
            ),
        ]
        for _ in range(1, num_authors):
            authors.append(
                AuthorData(
                    given_name=fake.first_name(),
                    family_name=fake.last_name(),
                    email=fake.email(),
                    affiliation=random.choice(UNIVERSITIES),
                    region_code=_pick_region(),
                    corresponding=False,
                )
            )

        paper_keywords = random.sample(
            keywords,
            k=random.randint(2, min(5, len(keywords))),
        )

        plan.paper = PaperService.create_paper(
            track=plan.track,
            owner=owner,
            title=_generate_title(),
            abstract=fake.paragraph(nb_sentences=8),
            contribution=fake.paragraph(nb_sentences=4),
            keywords=paper_keywords,
            authors=authors,
        )

    logger.info(f"    Created <green>{len(plans)}</> draft papers via PaperService")


# ── Submission Files ──────────────────────────────────────────────────────────


def _upload_submissions(plans: list[PaperPlan]) -> None:
    """Upload submission files for papers that will be submitted."""
    docx_template = (TEST_DATA_DIR / "sample.docx").read_bytes()

    count = 0
    for plan in plans:
        if plan.target_state == PaperState.DRAFT or plan.soft_deleted:
            continue

        use_pdf = random.random() < 0.8
        content = (
            _create_pdf_bytes(plan.paper, 1, "Paper submission")
            if use_pdf
            else _create_docx_bytes(
                docx_template,
                plan.paper,
                1,
                "Paper submission",
            )
        )
        ext = ".pdf" if use_pdf else ".docx"
        content_type = (
            "application/pdf"
            if use_pdf
            else (
                "application/"
                "vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        )

        RevisionService.create_submission(
            paper=plan.paper,
            file=SimpleUploadedFile(
                f"{plan.paper.code}{ext}",
                content,
                content_type,
            ),
            uploader=plan.owner,
            skip_cleanup=True,
        )
        count += 1

        # ~15% have a second revision
        if random.random() < 0.15:
            content = (
                _create_pdf_bytes(plan.paper, 2, "Paper submission")
                if use_pdf
                else _create_docx_bytes(
                    docx_template,
                    plan.paper,
                    2,
                    "Paper submission",
                )
            )
            RevisionService.create_submission(
                paper=plan.paper,
                file=SimpleUploadedFile(
                    f"{plan.paper.code}{ext}",
                    content,
                    content_type,
                ),
                uploader=plan.owner,
                skip_cleanup=True,
            )
            count += 1

    logger.info(f"    Uploaded <green>{count}</> submission files")


# ── Paper Submission (DRAFT -> SUBMITTED) ─────────────────────────────────────


def _submit_papers(plans: list[PaperPlan]) -> None:
    """Submit papers that should advance beyond DRAFT state."""
    count = 0
    for plan in plans:
        if plan.target_state == PaperState.DRAFT or plan.soft_deleted:
            continue
        PaperService.submit_paper(plan.paper, strict=False)
        count += 1

    logger.info(f"    Submitted <green>{count}</> papers")


# ── Paper Withdrawal ──────────────────────────────────────────────────────────


def _withdraw_papers(plans: list[PaperPlan]) -> None:
    """Withdraw papers that are flagged for withdrawal."""
    count = 0
    for plan in plans:
        if not plan.withdrawn:
            continue
        PaperService.withdraw_paper(plan.paper)
        count += 1

    logger.info(f"    Withdrew <green>{count}</> papers")


# ── Reviews ───────────────────────────────────────────────────────────────────


def _create_reviews(
    fake: Faker,
    plans: list[PaperPlan],
    reviewers: list[User],
    admins: list[User],
    conference: Conference,
    keywords: list[Keyword],
) -> None:
    """Assign reviewers and process review lifecycle using service methods."""
    review_count = 0
    comment_objects: list[AdminComment] = []
    # At least one admin is always present (chair + secretaries from _assign_roles).
    assigner = admins[0]

    # Only papers targeting UNDER_REVIEW or decided states get reviews.
    # Skip withdrawn and soft-deleted papers.
    needs_review_states = {PaperState.UNDER_REVIEW, *DECIDED_STATES}
    reviewable_plans = [
        plan
        for plan in plans
        if plan.target_state in needs_review_states
        and not plan.withdrawn
        and not plan.soft_deleted
    ]

    review_state_weights = {
        ReviewState.PENDING: 20,
        ReviewState.ACCEPTED: 15,
        ReviewState.SUBMITTED: 50,
        ReviewState.DECLINED: 10,
        ReviewState.CANCELLED: 5,
    }

    # Track assigned (paper_pk, reviewer_pk) to avoid duplicate assignments.
    assigned: set[tuple[int, int]] = set()

    for plan in reviewable_plans:
        paper = plan.paper
        num_reviews = random.randint(2, 3)
        candidates = random.sample(
            reviewers,
            k=min(num_reviews + 2, len(reviewers)),
        )

        count = 0
        for reviewer in candidates:
            if count >= num_reviews:
                break
            pair = (paper.pk, reviewer.pk)
            if pair in assigned:
                continue
            assigned.add(pair)

            target_review_state = _weighted(review_state_weights)

            # Step 1: Assign reviewer via service (handles SUBMITTED -> UNDER_REVIEW
            # transition on first assignment).
            review = ReviewService.assign_reviewer(
                paper=paper,
                reviewer=reviewer,
                assigner=assigner,
                mode="conference",
            )

            # Step 2: Respond to assignment (PENDING -> ACCEPTED or DECLINED).
            if target_review_state == ReviewState.DECLINED:
                ReviewService.respond_to_assignment(
                    review,
                    response=ReviewState.DECLINED,
                )
            elif target_review_state in (
                ReviewState.ACCEPTED,
                ReviewState.SUBMITTED,
                ReviewState.CANCELLED,
            ):
                ReviewService.respond_to_assignment(
                    review,
                    response=ReviewState.ACCEPTED,
                )

                # Step 3: Fill in scores for reviews that will be submitted.
                if target_review_state == ReviewState.SUBMITTED:
                    ReviewService.update_review(
                        review,
                        mode="admin",
                        originality=random.randint(1, 5),
                        significance=random.randint(1, 5),
                        technical=random.randint(1, 5),
                        reference=random.randint(1, 5),
                        presentation=random.randint(1, 5),
                        match_topic=random.randint(1, 5),
                        recommendation=random.randint(1, 5),
                        contribution=fake.paragraph(nb_sentences=3),
                        decision_reason=fake.paragraph(nb_sentences=2),
                        comments=fake.paragraph(nb_sentences=4),
                        confidential_remarks=(
                            fake.sentence() if random.random() < 0.3 else ""
                        ),
                    )

                    # Step 4: Submit the review.
                    ReviewService.submit_review(review, strict=False)

                elif target_review_state == ReviewState.CANCELLED:
                    ReviewService.cancel_review(review, mode="conference")

            # For PENDING state, no further action needed (already in PENDING).
            review_count += 1
            count += 1

        # ~10% of reviewed papers get an admin comment
        if random.random() < 0.1 and admins:
            comment_objects.append(
                AdminComment(
                    paper_id=paper.pk,
                    author=random.choice(admins),
                    content=fake.paragraph(nb_sentences=3),
                )
            )

    # Offline (imported) reviews for coverage
    offline_plans = [
        plan
        for plan in reviewable_plans
        if not plan.withdrawn and not plan.soft_deleted
    ][:5]
    for i, plan in enumerate(offline_plans):
        Review.objects.create(
            paper_id=plan.paper.pk,
            reviewer=None,
            offline_reviewer_name=f"External Reviewer {i + 1}",
            state=ReviewState.SUBMITTED,
            assigner=assigner,
            assignment_level=ReviewAssignmentLevel.CONFERENCE,
            submit_time=_past_time(1, 30),
            originality=random.randint(1, 5),
            significance=random.randint(1, 5),
            technical=random.randint(1, 5),
            reference=random.randint(1, 5),
            presentation=random.randint(1, 5),
            match_topic=random.randint(1, 5),
            recommendation=random.randint(1, 5),
            contribution=fake.paragraph(nb_sentences=3),
            decision_reason=fake.paragraph(nb_sentences=2),
            comments=fake.paragraph(nb_sentences=4),
        )
        review_count += 1

    AdminComment.objects.bulk_create(comment_objects)

    # Reviewer notification logs (~50% of reviewers)
    notif_reviewers = random.sample(reviewers, k=len(reviewers) // 2)
    ReviewerNotificationLog.objects.bulk_create(
        [
            ReviewerNotificationLog(
                conference=conference,
                reviewer=r,
                last_notification_time=_past_time(1, 14),
            )
            for r in notif_reviewers
        ]
    )

    # User conference profiles for reviewers
    ucp_objects: list[UserConferenceProfile] = []
    ucp_kw_through: list[tuple[int, Keyword]] = []
    for i, r in enumerate(reviewers):
        ucp_objects.append(
            UserConferenceProfile(
                user=r,
                conference=conference,
                desired_paper_count=random.randint(2, 8),
            )
        )
        for kw in random.sample(keywords, k=random.randint(2, 5)):
            ucp_kw_through.append((i, kw))

    UserConferenceProfile.objects.bulk_create(ucp_objects)
    UCPKeywordThrough = UserConferenceProfile.interested_keywords.through
    UCPKeywordThrough.objects.bulk_create(
        [
            UCPKeywordThrough(
                userconferenceprofile_id=ucp_objects[idx].pk,
                keyword_id=kw.pk,
            )
            for idx, kw in ucp_kw_through
        ]
    )

    logger.info(
        f"    Created <green>{review_count}</> reviews, "
        f"<green>{len(comment_objects)}</> admin comments",
    )


# ── Paper Decisions ───────────────────────────────────────────────────────────


def _decide_papers(plans: list[PaperPlan], admins: list[User]) -> None:
    """Decide papers using PaperService for proper state transitions."""
    count = 0
    for i, plan in enumerate(plans):
        if plan.target_state not in DECIDED_STATES or plan.soft_deleted:
            continue
        PaperService.decide_paper(
            paper=plan.paper,
            decider=admins[i % len(admins)],
            state=PaperState(plan.target_state),
            note="",
        )
        count += 1

    logger.info(f"    Decided <green>{count}</> papers")


# ── Acceptance Letters ────────────────────────────────────────────────────────


def _create_acceptance_letters(conference: Conference, plans: list[PaperPlan]) -> None:
    """Create acceptance letters for accepted papers that will be announced.

    Must be called before announcement, since announce_papers requires letters
    for accepted papers. Uses the same resolve-and-compile pipeline as the API
    endpoint to produce real Typst-rendered PDFs with the full context.
    """
    compile_letter = async_to_sync(_resolve_and_compile_letter)

    count = 0
    for plan in plans:
        if plan.target_state not in ACCEPTED_STATES:
            continue
        if not plan.announced or plan.soft_deleted:
            continue

        paper = plan.paper
        _, _, pdf_bytes, context = compile_letter(
            conference.name,
            paper.code,
            ACCEPTANCE_LETTER_TEMPLATE,
            {},
        )
        letter = AcceptanceLetter(
            paper=paper,
            template=ACCEPTANCE_LETTER_TEMPLATE,
            context=context,
        )
        letter.rendered_pdf.save(
            f"{paper.code}-acceptance.pdf",
            ContentFile(pdf_bytes),
            save=True,
        )
        count += 1

    logger.info(f"    Created <green>{count}</> acceptance letters")


# ── Paper Announcement ────────────────────────────────────────────────────────


def _announce_papers(conference: Conference, plans: list[PaperPlan]) -> None:
    """Announce decided papers via PaperService for canonical eligibility checks."""
    codes = [
        plan.paper.code
        for plan in plans
        if plan.announced
        and not plan.soft_deleted
        and plan.target_state in DECIDED_STATES
    ]
    announced_codes = async_to_sync(PaperService.announce_papers)(conference, codes)
    logger.info(f"    Announced <green>{len(announced_codes)}</> papers")


# ── Finals ────────────────────────────────────────────────────────────────────


def _create_finals(plans: list[PaperPlan]) -> None:
    """Create final submissions for announced accepted papers."""
    docx_template = (TEST_DATA_DIR / "sample.docx").read_bytes()

    count = 0
    for plan in plans:
        if plan.target_state not in ACCEPTED_STATES:
            continue
        paper = plan.paper
        if paper.announce_time is None or plan.soft_deleted:
            continue
        if random.random() > 0.7:
            continue

        use_docx = random.random() < 0.7
        source_bytes = (
            _create_docx_bytes(docx_template, paper, 1, "Final source")
            if use_docx
            else _create_zip_bytes(paper, 1)
        )
        source_extension = ".docx" if use_docx else ".zip"
        source_content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if use_docx
            else "application/zip"
        )

        RevisionService.create_final(
            paper=paper,
            source_file=SimpleUploadedFile(
                f"{paper.code}-final{source_extension}",
                source_bytes,
                source_content_type,
            ),
            viewable_file=SimpleUploadedFile(
                f"{paper.code}-final.pdf",
                _create_pdf_bytes(paper, 1, "Final viewable version"),
                "application/pdf",
            ),
            uploader=plan.owner,
            enforce_limit=False,
        )
        count += 1

    logger.info(f"    Created <green>{count}</> finals")


# ── Paper Soft Deletion ──────────────────────────────────────────────────────


def _soft_delete_papers(plans: list[PaperPlan]) -> None:
    """Soft-delete papers flagged for deletion via PaperService."""
    count = 0
    for plan in plans:
        if not plan.soft_deleted:
            continue
        # Use admin mode to allow deletion regardless of state.
        PaperService.delete_paper(paper=plan.paper, mode="admin")
        count += 1

    logger.info(f"    Soft-deleted <green>{count}</> papers")


# ── Paper Refresh ─────────────────────────────────────────────────────────────


def _refresh_papers(plans: list[PaperPlan]) -> None:
    """Refresh all paper objects from DB after state mutations.

    Service methods re-fetch internally and return updated objects, but the
    script passes the original plan.paper references to downstream code.
    This bulk refresh ensures attributes like state, delete_time, and
    announce_time are current.
    """
    paper_pks = [plan.paper.pk for plan in plans]
    refreshed = {
        p.pk: p
        for p in Paper.objects.filter(pk__in=paper_pks).select_related(
            "track",
            "owner",
        )
    }
    for plan in plans:
        plan.paper = refreshed[plan.paper.pk]


# ── Registrations ─────────────────────────────────────────────────────────────


def _create_registrations(
    fake: Faker,
    users: list[User],
    profiles: dict[int, dict[str, str]],
    conference: Conference,
    papers: list[Paper],
    att_types: dict[str, AttendanceType],
) -> list[Registration]:
    reg_state_weights = {
        RegistrationState.PENDING: 35,
        RegistrationState.CONFIRMED: 55,
        RegistrationState.CANCELLED: 10,
    }
    titles = list(RegistrationTitle)

    # Author registrations for accepted announced papers
    accepted_announced = [
        p
        for p in papers
        if p.state in ACCEPTED_STATES
        and p.announce_time is not None
        and p.delete_time is None
    ]

    reg_objects: list[Registration] = []
    registered_users: set[int] = set()

    for paper in accepted_announced:
        if random.random() > 0.7:
            continue
        owner = paper.owner
        if owner.pk in registered_users:
            continue
        registered_users.add(owner.pk)
        p = profiles.get(owner.pk, {})
        registration = Registration.objects.create(
            conference=conference,
            state=RegistrationState.PENDING,
            user=owner,
            paper=paper,
            attendance_type=att_types["Author"],
            title=random.choice(titles),
            given_name=p.get("given_name", ""),
            family_name=p.get("family_name", ""),
            affiliation=p.get("affiliation", ""),
            region_code=p.get("region_code", ""),
            email=owner.email,
            phone=fake.phone_number()[:20],
            receipt_title=p.get("affiliation", ""),
        )
        target_state = _weighted(
            {
                RegistrationState.PENDING: 20,
                RegistrationState.CONFIRMED: 75,
                RegistrationState.CANCELLED: 5,
            }
        )
        if target_state == RegistrationState.CONFIRMED:
            registration = RegistrationService.update_registration(
                registration,
                mode="admin",
                state=RegistrationState.CONFIRMED,
            )
        elif target_state == RegistrationState.CANCELLED:
            registration = RegistrationService.cancel_registration(registration)
        reg_objects.append(registration)

    # Regular and student registrations
    regular_types = [att_types["Regular Attendee"], att_types["Student"]]
    num_regular = max(20, len(papers) // 5)
    regular_pool = [u for u in users if u.pk not in registered_users]
    random.shuffle(regular_pool)

    for user in regular_pool[:num_regular]:
        if user.pk in registered_users:
            continue
        registered_users.add(user.pk)
        p = profiles.get(user.pk, {})
        registration = Registration.objects.create(
            conference=conference,
            state=RegistrationState.PENDING,
            user=user,
            attendance_type=random.choice(regular_types),
            title=random.choice(titles),
            given_name=p.get("given_name", ""),
            family_name=p.get("family_name", ""),
            affiliation=p.get("affiliation", ""),
            region_code=p.get("region_code", ""),
            email=user.email,
            phone=fake.phone_number()[:20],
            receipt_title=p.get("affiliation", ""),
        )
        target_state = _weighted(reg_state_weights)
        if target_state == RegistrationState.CONFIRMED:
            registration = RegistrationService.update_registration(
                registration,
                mode="admin",
                state=RegistrationState.CONFIRMED,
            )
        elif target_state == RegistrationState.CANCELLED:
            registration = RegistrationService.cancel_registration(registration)
        reg_objects.append(registration)

    logger.info(f"    Created <green>{len(reg_objects)}</> registrations")
    return reg_objects


# ── Payments ──────────────────────────────────────────────────────────────────


def _create_payments(
    conference: Conference,
    registrations: list[Registration],
    spec: dict[str, Any],
) -> None:
    currency = spec["currency"]
    lo, hi = spec["payment_amount_range"]

    confirmed = [r for r in registrations if r.state == RegistrationState.CONFIRMED]
    pending = [r for r in registrations if r.state == RegistrationState.PENDING]
    cancelled = [r for r in registrations if r.state == RegistrationState.CANCELLED]

    count = 0

    # Payments for confirmed registrations
    for i, reg in enumerate(confirmed):
        amount = Decimal(random.randint(lo, hi))
        PaymentService.create_payment(
            Payment(
                conference=conference,
                amount=amount,
                currency=currency,
                type=PaymentType.PAYMENT,
                method=random.choice(list(PaymentMethod)),
                reference=f"TXN-{conference.name}-{i + 1:04d}",
                note="",
            ),
            items=[
                PaymentItemData(
                    registration=reg.uid,
                    amount=amount,
                    description="Registration fee",
                ),
            ],
        )
        count += 1

    # Some payments for pending registrations (~30%)
    for i, reg in enumerate(pending):
        if random.random() > 0.3:
            continue
        amount = Decimal(random.randint(lo, hi))
        PaymentService.create_payment(
            Payment(
                conference=conference,
                amount=amount,
                currency=currency,
                type=PaymentType.PAYMENT,
                method=random.choice(list(PaymentMethod)),
                reference=f"TXN-{conference.name}-P{i + 1:04d}",
            ),
            items=[
                PaymentItemData(
                    registration=reg.uid,
                    amount=amount,
                    description="Registration fee (pending confirmation)",
                ),
            ],
        )
        count += 1

    # Refunds for some cancelled registrations
    for i, reg in enumerate(cancelled):
        if random.random() > 0.5:
            continue
        amount = Decimal(random.randint(lo // 2, lo))
        PaymentService.create_payment(
            Payment(
                conference=conference,
                amount=amount,
                currency=currency,
                type=PaymentType.REFUND,
                method=PaymentMethod.CREDIT_CARD,
                reference=f"TXN-{conference.name}-R{i + 1:04d}",
                note="Cancellation refund",
            ),
            items=[
                PaymentItemData(
                    registration=reg.uid,
                    amount=amount,
                    description="Refund",
                ),
            ],
        )
        count += 1

    # One soft-deleted payment
    if confirmed:
        amount = Decimal(random.randint(lo, hi))
        payment = PaymentService.create_payment(
            Payment(
                conference=conference,
                amount=amount,
                currency=currency,
                type=PaymentType.PAYMENT,
                method=PaymentMethod.CREDIT_CARD,
                reference=f"TXN-{conference.name}-DEL",
                note="Deleted payment example",
            ),
            items=[
                PaymentItemData(
                    registration=confirmed[0].uid,
                    amount=amount,
                    description="Deleted payment item",
                ),
            ],
        )
        payment.delete_time = timezone.now()
        payment.save(update_fields=["delete_time", "update_time"])
        count += 1

    logger.info(f"    Created <green>{count}</> payments")


# ── Invitations ───────────────────────────────────────────────────────────────


def _create_invitations(
    fake: Faker,
    users: list[User],
    admins: list[User],
    conference: Conference,
    tracks: list[Track],
    keywords: list[Keyword],
) -> None:
    inviter = admins[0] if admins else None
    if not inviter:
        return

    num_invitations = random.randint(10, 20)
    used_emails: set[str] = set()
    count = 0

    for i in range(num_invitations):
        # Determine state: 50% pending, 30% accepted, 20% rejected
        roll = random.random()
        if roll < 0.5:
            state = "pending"
        elif roll < 0.8:
            state = "accepted"
        else:
            state = "rejected"

        if state == "accepted" and i < len(users):
            user = users[-(i + 1)]
            email = user.email
        else:
            email = f"invite-{conference.name.lower()}-{i}@example.com"
            user = None

        if email in used_emails:
            email = f"invite-dup-{conference.name.lower()}-{i}@example.com"
        used_emails.add(email)

        # Determine roles
        conf_role = random.choices(
            [ConferenceRole.REVIEWER, ConferenceRole.MEMBER],
            weights=[80, 20],
        )[0]
        track_roles: dict[Track, list[TrackRole]] = {}
        if random.random() < 0.3 and tracks:
            track_roles = {random.choice(tracks): [TrackRole.REVIEWER]}

        interested = random.sample(keywords, k=random.randint(1, 4))

        invitation = InvitationService.create_invitation(
            conference=conference,
            inviter=inviter,
            invitee_email=email,
            given_name=fake.first_name(),
            family_name=fake.last_name(),
            affiliation=random.choice(UNIVERSITIES),
            region_code=_pick_region(),
            desired_paper_count=random.randint(3, 8),
            interested_keywords=interested,
            conference_roles=[conf_role],
            track_roles=track_roles,
        )

        # Simulate email send metadata
        invitation.last_email_send_time = timezone.now()
        invitation.email_send_count = random.randint(1, 3)
        invitation.save(
            update_fields=["last_email_send_time", "email_send_count", "update_time"]
        )

        if state == "accepted" and user is not None:
            InvitationService.redeem_invitation(invitation, user)
        elif (
            state == "rejected"
            and invitation.state != invitation.State.ACCEPTED
            and invitation.reject_time is None
        ):
            invitation.reject_time = timezone.now()
            invitation.save(update_fields=["reject_time", "update_time"])

        count += 1

    logger.info(f"    Created <green>{count}</> invitations")


# ── Documents (Receipts, Conference Files) ────────────────────────────────────


def _create_documents(
    conference: Conference,
    registrations: list[Registration],
) -> None:
    compile_receipt = async_to_sync(_resolve_and_compile_receipt)

    # Receipts for ~50% of confirmed registrations
    confirmed_regs = [
        r for r in registrations if r.state == RegistrationState.CONFIRMED
    ]
    receipt_count = 0
    for reg in confirmed_regs:
        if random.random() > 0.5:
            continue
        _, _, pdf_bytes, context = compile_receipt(
            conference.name,
            reg.uid,
            RECEIPT_TEMPLATE,
            {},
        )
        receipt = Receipt(
            registration=reg,
            template=RECEIPT_TEMPLATE,
            context=context,
        )
        receipt.rendered_pdf.save(
            f"{reg.reference_code}-receipt.pdf",
            ContentFile(pdf_bytes),
            save=True,
        )
        receipt_count += 1

    # Conference files (2-3 per conference)
    sample_pdf = (TEST_DATA_DIR / "sample.pdf").read_bytes()
    file_specs = [
        ("submission-template", "submission-template.pdf", sample_pdf),
        ("registration-form", "registration-form.pdf", sample_pdf),
    ]
    if random.random() < 0.6:
        png_bytes = (TEST_DATA_DIR / "sample.png").read_bytes()
        file_specs.append(("conference-logo", "logo.png", png_bytes))

    for name, filename, content in file_specs:
        cf = ConferenceFile(conference=conference, name=name, filename=filename)
        cf.file.save(filename, ContentFile(content), save=True)

    logger.info(
        f"    Created <green>{receipt_count}</> receipts, "
        f"<green>{len(file_specs)}</> conference files",
    )


# ── Email Send Logs ───────────────────────────────────────────────────────────


def _create_email_logs(
    admins: list[User],
    conference: Conference,
) -> None:
    sender = admins[0] if admins else None
    log_objects: list[EmailSendLog] = []

    # Simulate some acceptance letter and receipt emails
    for i in range(random.randint(5, 15)):
        log_objects.append(
            EmailSendLog(
                conference=conference,
                correlation_id=f"acceptance-letter:paper-{i}",
                send_time=_past_time(1, 30),
                sender=sender,
            )
        )
    for i in range(random.randint(3, 10)):
        log_objects.append(
            EmailSendLog(
                conference=conference,
                correlation_id=f"receipt:reg-{i}",
                send_time=_past_time(1, 30),
                sender=sender,
            )
        )

    EmailSendLog.objects.bulk_create(log_objects)
    logger.info(f"    Created <green>{len(log_objects)}</> email send logs")


# ── Duplicate Detection Data ─────────────────────────────────────────────────


def _create_duplicate_data(
    papers: list[Paper],
    admins: list[User],
    conference: Conference,
) -> None:
    active_papers = [p for p in papers if p.delete_time is None]
    if len(active_papers) < 4:
        return

    # Create 2 reports (one success, one failed)
    success_report = DuplicateReport.objects.create(state=DuplicateReportState.SUCCESS)
    DuplicateReport.objects.create(
        state=DuplicateReportState.FAILED,
        error_message="Paper count exceeded safety threshold (simulated).",
    )

    # Create some matches in the success report
    match_objects: list[DuplicateMatch] = []
    num_matches = min(8, len(active_papers) // 5)
    pairs_used: set[tuple[int, int]] = set()

    for _ in range(num_matches):
        a, b = random.sample(active_papers, 2)
        pair = (min(a.pk, b.pk), max(a.pk, b.pk))
        if pair in pairs_used:
            continue
        pairs_used.add(pair)
        match_objects.append(
            DuplicateMatch(
                report=success_report,
                paper_a_id=pair[0],
                paper_b_id=pair[1],
                match_type=random.choice(list(DuplicateMatchType)),
                score=round(random.uniform(0.6, 1.0), 3),
            )
        )

    DuplicateMatch.objects.bulk_create(match_objects)

    # Acknowledge some matches
    if match_objects and admins:
        for match in match_objects[:3]:
            DuplicateAcknowledgment.objects.create(
                paper_a_id=match.paper_a_id,
                paper_b_id=match.paper_b_id,
                conference=conference,
                user=random.choice(admins),
                note="Reviewed and acknowledged." if random.random() < 0.5 else "",
            )

    logger.info(
        f"    Created 2 duplicate reports, <green>{len(match_objects)}</> matches",
    )


# ── IEEE eCopyright ───────────────────────────────────────────────────────────


def _create_ieee_ecopyright(
    conference: Conference,
    tracks: list[Track],
    papers: list[Paper],
) -> None:
    config = IEEEeCopyrightConfig.objects.create(
        conference=conference,
        publication_title=f"Proceedings of {conference.display_name}",
        article_source=conference.name,
    )
    # Exempt the last track (if multiple)
    if len(tracks) > 1:
        config.exempt_tracks.set([tracks[-1]])

    # Create consents for some accepted papers
    accepted = [
        p
        for p in papers
        if p.state in ACCEPTED_STATES
        and p.announce_time is not None
        and p.delete_time is None
    ]

    consent_objects: list[IEEEeCopyrightConsent] = []
    for paper in accepted:
        if random.random() > 0.4:
            continue
        consent_objects.append(
            IEEEeCopyrightConsent(
                paper_id=paper.pk,
                raw_response={
                    "title": paper.title,
                    "articleNumber": paper.code,
                    "copyrightStatus": "accepted",
                    "timestamp": _past_time(1, 30).isoformat(),
                },
            )
        )

    IEEEeCopyrightConsent.objects.bulk_create(consent_objects)
    logger.info(
        f"    Created IEEE eCopyright config with "
        f"<green>{len(consent_objects)}</> consents",
    )
