"""Populate the database with dummy data for development testing."""

import datetime
from decimal import Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone
from loguru import logger

from app.conference.models import (
    AttendanceType,
    CodePool,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    ConferenceVisibility,
    Invitation,
    InvitationConferenceRoleEntry,
    InvitationTrackRoleEntry,
    Keyword,
    Paper,
    PaperAuthor,
    PaperDecision,
    PaperDecisionState,
    PaperState,
    PaperSubmission,
    Payment,
    PaymentCurrency,
    PaymentItem,
    PaymentMethod,
    PaymentType,
    Profile,
    Registration,
    RegistrationState,
    RegistrationTitle,
    Review,
    ReviewAssignmentLevel,
    ReviewState,
    Track,
    TrackRole,
    TrackRoleAssignment,
    TrackVisibility,
)
from app.core.models import GlobalRole, GlobalRoleAssignment, User

LOG_DEPTH = 1
logger = logger.opt(colors=True, depth=LOG_DEPTH)

PASSWORD = "password"  # noqa: S105
TEST_DATA_DIR = Path(__file__).parent.parent / "tests" / "data"


def run() -> None:
    logger.info("Seeding database with dummy data...")
    users = seed_users()
    keywords = seed_keywords()
    conference, tracks = seed_conference(keywords)
    seed_roles(users, conference, tracks)
    seed_papers(users, conference, tracks, keywords)
    seed_paper_submissions(users, conference)
    seed_reviews(users, conference)
    seed_registrations(users, conference)
    seed_payments(conference)
    seed_invitations(users, conference, tracks)
    logger.info("Seeding complete.")


def seed_users() -> dict[str, User]:
    logger.info("Seeding users...")
    users: dict[str, User] = {}

    user_specs = [
        # Conference-level roles
        ("conf-chair", "Conference", "Chair"),
        ("conf-secretary", "Conference", "Secretary"),
        ("conf-reviewer", "Conference", "Reviewer"),
        # Track-level roles
        ("track-a-chair", "Track A", "Chair"),
        ("track-a-reviewer", "Track A", "Reviewer"),
        ("track-b-chair", "Track B", "Chair"),
        # Regular users
        ("author", "Author", "User"),
        ("another-author", "Another", "Author"),
        # Global admin
        ("global-admin", "Global", "Admin"),
        # Member (for member-only visibility testing)
        ("member", "Member", "User"),
    ]

    for username, first_name, last_name in user_specs:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "is_active": True,
            },
        )
        if created:
            user.set_password(PASSWORD)
            user.save()
            Profile.objects.create(
                user=user,
                given_name=first_name,
                family_name=last_name,
                affiliation="Example University",
                region_code="US",
            )
            logger.info(f"    Created user: <green>{username}</>")
        else:
            logger.info(f"    User already exists: <yellow>{username}</>")
        users[username] = user

    GlobalRoleAssignment.objects.get_or_create(
        user=users["global-admin"],
        role=GlobalRole.ADMIN,
    )

    superuser, created = User.objects.get_or_create(
        username="superuser",
        defaults={
            "email": "superuser@example.com",
            "is_active": True,
            "is_staff": True,
            "is_superuser": True,
        },
    )
    if created:
        superuser.set_password(PASSWORD)
        superuser.save()
        Profile.objects.create(
            user=superuser,
            given_name="Super",
            family_name="User",
            affiliation="Example University",
            region_code="US",
        )
        logger.info("    Created superuser: <green>superuser</>")
    else:
        logger.info("    Superuser already exists: <yellow>superuser</>")
    users["superuser"] = superuser

    return users


def seed_keywords() -> dict[str, Keyword]:
    logger.info("Seeding keywords...")
    keywords: dict[str, Keyword] = {}

    keyword_texts = [
        "Machine Learning",
        "Deep Learning",
        "Natural Language Processing",
        "Computer Vision",
        "Reinforcement Learning",
        "Neural Networks",
        "Data Mining",
        "Big Data",
        "Cloud Computing",
        "Distributed Systems",
        "Software Engineering",
        "Security",
    ]

    for text in keyword_texts:
        keyword, created = Keyword.objects.get_or_create(text=text)
        key = text.lower().replace(" ", "-")
        keywords[key] = keyword
        if created:
            logger.info(f"    Created keyword: <green>{text}</>")
        else:
            logger.info(f"    Keyword already exists: <yellow>{text}</>")

    return keywords


def seed_conference(
    keywords: dict[str, Keyword],
) -> tuple[Conference, dict[str, Track]]:
    logger.info("Seeding conference and tracks...")

    today = datetime.date.today()
    conference, created = Conference.objects.get_or_create(
        name="TEST-1000",
        defaults={
            "display_name": "Test Conference 1000",
            "active": True,
            "visibility": ConferenceVisibility.PUBLIC,
            "registration_enabled": True,
            "start_date": today + datetime.timedelta(days=60),
            "end_date": today + datetime.timedelta(days=63),
            "location": "Tokyo, Japan",
            "paper_submission_instructions": (
                "## Submission Guidelines\n\n"
                "Please submit your paper in **PDF format** with the following:\n\n"
                "- Maximum 10 pages (excluding references)\n"
                "- Use the provided LaTeX or Word template\n"
                "- Double-blind review: remove author names and affiliations\n"
                "- Ensure all figures and tables are readable\n"
            ),
            "paper_final_instructions": (
                "## Camera-Ready Guidelines\n\n"
                "Congratulations on your paper acceptance! Please prepare:\n\n"
                "1. **Source files**: ZIP archive with LaTeX/Word source\n"
                "2. **PDF**: Final formatted PDF (max 12 pages)\n"
                "3. Include author names and affiliations\n"
                "4. Address all reviewer comments\n"
            ),
        },
    )
    if created:
        logger.info(f"    Created conference: <green>{conference.name}</>")
    else:
        logger.info(f"    Conference already exists: <yellow>{conference.name}</>")

    conference_keywords = [
        keywords["machine-learning"],
        keywords["deep-learning"],
        keywords["natural-language-processing"],
        keywords["computer-vision"],
        keywords["software-engineering"],
        keywords["security"],
    ]
    conference.keywords.set(conference_keywords)
    logger.info(f"    Bound {len(conference_keywords)} keywords to conference")

    code_pool, _ = CodePool.objects.get_or_create(
        conference=conference,
        prefix="TP-",
        defaults={"name": "Main Pool"},
    )

    tracks: dict[str, Track] = {}
    track_specs = [
        ("track-a", "Track A: Main Research"),
        ("track-b", "Track B: Applications"),
    ]

    for ordering, (key, display_name) in enumerate(track_specs):
        track, created = Track.objects.get_or_create(
            conference=conference,
            display_name=display_name,
            defaults={
                "code_pool": code_pool,
                "active": True,
                "ordering": ordering,
                "visibility": TrackVisibility.PUBLIC,
                "submissions_enabled": True,
            },
        )
        if created:
            logger.info(f"    Created track: <green>{display_name}</>")
        else:
            logger.info(f"    Track already exists: <yellow>{display_name}</>")
        tracks[key] = track

    attendance_specs = [
        ("Author", False, True),
        ("Regular Attendee", False, False),
        ("Student", False, False),
        ("VIP", True, False),
    ]
    for ordering, (display_name, admin_only, paper_required) in enumerate(
        attendance_specs
    ):
        AttendanceType.objects.get_or_create(
            conference=conference,
            display_name=display_name,
            defaults={
                "ordering": ordering,
                "admin_only": admin_only,
                "paper_required": paper_required,
            },
        )

    return conference, tracks


def seed_roles(
    users: dict[str, User],
    conference: Conference,
    tracks: dict[str, Track],
) -> None:
    logger.info("Seeding role assignments...")

    conference_roles = [
        ("conf-chair", ConferenceRole.CHAIR),
        ("conf-secretary", ConferenceRole.SECRETARY),
        ("conf-reviewer", ConferenceRole.REVIEWER),
        ("member", ConferenceRole.MEMBER),
    ]
    for username, conf_role in conference_roles:
        _, created = ConferenceRoleAssignment.objects.get_or_create(
            conference=conference,
            user=users[username],
            role=conf_role,
        )
        if created:
            logger.info(
                f"    Assigned <green>{conf_role}</> to {username} (conference)"
            )

    track_roles = [
        ("track-a-chair", "track-a", TrackRole.CHAIR),
        ("track-a-reviewer", "track-a", TrackRole.REVIEWER),
        ("track-b-chair", "track-b", TrackRole.CHAIR),
    ]
    for username, track_key, track_role in track_roles:
        _, created = TrackRoleAssignment.objects.get_or_create(
            track=tracks[track_key],
            user=users[username],
            role=track_role,
        )
        if created:
            logger.info(
                f"    Assigned <green>{track_role}</> to {username} "
                f"({tracks[track_key].display_name})"
            )


def seed_papers(
    users: dict[str, User],
    conference: Conference,
    tracks: dict[str, Track],
    keywords: dict[str, Keyword],
) -> None:
    logger.info("Seeding papers...")

    author = users["author"]
    another_author = users["another-author"]
    chair = users["conf-chair"]
    now = timezone.now()

    paper_keyword_specs: dict[str, list[str]] = {
        "TP-001": ["machine-learning", "deep-learning"],
        "TP-002": ["natural-language-processing", "machine-learning"],
        "TP-003": ["computer-vision", "deep-learning", "neural-networks"],
        "TP-004": ["machine-learning", "data-mining"],
        "TP-005": ["reinforcement-learning", "neural-networks"],
        "TP-006": ["cloud-computing", "distributed-systems"],
        "TP-007": ["software-engineering", "security"],
        "TP-009": ["big-data", "cloud-computing"],
        "TP-010": ["machine-learning", "software-engineering"],
    }

    paper_specs = [
        # (code, title, state, track, owner, withdrawn, announced, decided_state)
        (
            "TP-001",
            "Draft Paper Example",
            PaperState.DRAFT,
            "track-a",
            author,
            False,
            False,
            None,
        ),
        (
            "TP-002",
            "Submitted Paper Example",
            PaperState.SUBMITTED,
            "track-a",
            author,
            False,
            False,
            None,
        ),
        (
            "TP-003",
            "Paper Under Review",
            PaperState.UNDER_REVIEW,
            "track-a",
            author,
            False,
            False,
            None,
        ),
        (
            "TP-004",
            "Accepted Paper (Announced)",
            PaperState.ACCEPTED,
            "track-a",
            author,
            False,
            True,
            PaperDecisionState.ACCEPTED,
        ),
        (
            "TP-005",
            "Accepted Paper (Not Announced)",
            PaperState.ACCEPTED,
            "track-a",
            author,
            False,
            False,
            PaperDecisionState.ACCEPTED,
        ),
        (
            "TP-006",
            "Rejected Paper",
            PaperState.REJECTED,
            "track-a",
            author,
            False,
            True,
            PaperDecisionState.REJECTED,
        ),
        (
            "TP-007",
            "Accepted with Revision Needed",
            PaperState.ACCEPTED_REVISION_NEEDED,
            "track-a",
            author,
            False,
            True,
            PaperDecisionState.ACCEPTED_REVISION_NEEDED,
        ),
        (
            "TP-008",
            "Withdrawn Paper",
            PaperState.SUBMITTED,
            "track-a",
            author,
            True,
            False,
            None,
        ),
        # Track B papers
        (
            "TP-009",
            "Track B Submitted Paper",
            PaperState.SUBMITTED,
            "track-b",
            author,
            False,
            False,
            None,
        ),
        (
            "TP-010",
            "Track B Accepted Paper",
            PaperState.ACCEPTED,
            "track-b",
            author,
            False,
            True,
            PaperDecisionState.ACCEPTED,
        ),
        # Paper by another author (for isolation testing)
        (
            "TP-011",
            "Another Author Draft",
            PaperState.DRAFT,
            "track-a",
            another_author,
            False,
            False,
            None,
        ),
        (
            "TP-012",
            "Another Author Submitted",
            PaperState.SUBMITTED,
            "track-a",
            another_author,
            False,
            False,
            None,
        ),
    ]

    for (
        code,
        title,
        state,
        track_key,
        owner,
        withdrawn,
        announced,
        decided_state,
    ) in paper_specs:
        paper, created = Paper.objects.get_or_create(
            conference=conference,
            code=code,
            defaults={
                "track": tracks[track_key],
                "state": state,
                "owner": owner,
                "title": title,
                "abstract": f"This is the abstract for {title}.",
                "contribution": f"The contribution of {title} is significant.",
                "withdraw_time": now if withdrawn else None,
                "announce_time": now if announced else None,
                "submit_time": now if state != PaperState.DRAFT else None,
            },
        )

        if created:
            logger.info(f"    Created paper: <green>{code}</> ({state})")

            PaperAuthor.objects.create(
                paper=paper,
                ordering=0,
                given_name=owner.profile.given_name,
                family_name=owner.profile.family_name,
                email=owner.email,
                affiliation="Example University",
                region_code="US",
                corresponding=True,
            )
            PaperAuthor.objects.create(
                paper=paper,
                ordering=1,
                given_name="Co",
                family_name="Author",
                email="coauthor@example.com",
                affiliation="Partner Institute",
                region_code="GB",
                corresponding=False,
            )

            if decided_state:
                PaperDecision.objects.create(
                    paper=paper,
                    decider=chair,
                    state=decided_state,
                    note=f"Decision note for {code}",
                )

            if code in paper_keyword_specs:
                paper_kws = [keywords[k] for k in paper_keyword_specs[code]]
                paper.keywords.set(paper_kws)
                logger.info(f"        Bound {len(paper_kws)} keywords")
        else:
            logger.info(f"    Paper already exists: <yellow>{code}</>")


def seed_paper_submissions(
    users: dict[str, User],
    conference: Conference,
) -> None:
    logger.info("Seeding paper submissions...")

    author = users["author"]
    sample_pdf = TEST_DATA_DIR / "sample.pdf"
    sample_docx = TEST_DATA_DIR / "sample.docx"

    submission_specs = [
        # (paper_code, file_path, revisions)
        ("TP-002", sample_pdf, [0]),
        ("TP-003", sample_pdf, [0]),
        ("TP-004", sample_pdf, [0, 1]),  # Multiple revisions
        ("TP-009", sample_docx, [0]),
    ]

    for paper_code, file_path, revisions in submission_specs:
        paper = Paper.objects.filter(
            conference=conference,
            code=paper_code,
        ).first()
        if not paper:
            continue

        for revision in revisions:
            existing = PaperSubmission.objects.filter(
                paper=paper,
                revision=revision,
            ).exists()
            if existing:
                logger.info(
                    f"    Submission already exists: <yellow>{paper_code}</> "
                    f"rev{revision}"
                )
                continue

            file_content = file_path.read_bytes()
            submission = PaperSubmission(
                paper=paper,
                revision=revision,
                uploader=author,
            )
            submission.file.save(
                file_path.name,
                ContentFile(file_content),
                save=True,
            )
            logger.info(
                f"    Created submission: <green>{paper_code}</> "
                f"rev{revision} ({file_path.name})"
            )


def seed_reviews(
    users: dict[str, User],
    conference: Conference,
) -> None:
    logger.info("Seeding reviews...")

    conf_reviewer = users["conf-reviewer"]
    track_a_reviewer = users["track-a-reviewer"]
    chair = users["conf-chair"]
    now = timezone.now()

    papers = Paper.objects.filter(
        conference=conference,
        state__in=[
            PaperState.SUBMITTED,
            PaperState.UNDER_REVIEW,
            PaperState.ACCEPTED,
            PaperState.REJECTED,
            PaperState.ACCEPTED_REVISION_NEEDED,
        ],
        delete_time__isnull=True,
    )

    review_specs = [
        # (paper_code, reviewer, state, assignment_level, scores)
        (
            "TP-002",
            conf_reviewer,
            ReviewState.PENDING,
            ReviewAssignmentLevel.CONFERENCE,
            None,
        ),
        (
            "TP-003",
            conf_reviewer,
            ReviewState.ACCEPTED,
            ReviewAssignmentLevel.CONFERENCE,
            None,
        ),
        (
            "TP-003",
            track_a_reviewer,
            ReviewState.SUBMITTED,
            ReviewAssignmentLevel.TRACK,
            True,
        ),
        (
            "TP-004",
            conf_reviewer,
            ReviewState.SUBMITTED,
            ReviewAssignmentLevel.CONFERENCE,
            True,
        ),
        (
            "TP-004",
            track_a_reviewer,
            ReviewState.SUBMITTED,
            ReviewAssignmentLevel.TRACK,
            True,
        ),
        (
            "TP-006",
            conf_reviewer,
            ReviewState.SUBMITTED,
            ReviewAssignmentLevel.CONFERENCE,
            True,
        ),
        (
            "TP-009",
            conf_reviewer,
            ReviewState.PENDING,
            ReviewAssignmentLevel.CONFERENCE,
            None,
        ),
    ]

    for paper_code, reviewer, state, level, has_scores in review_specs:
        paper = papers.filter(code=paper_code).first()
        if not paper:
            continue

        _, created = Review.objects.get_or_create(
            paper=paper,
            reviewer=reviewer,
            defaults={
                "state": state,
                "assigner": chair,
                "assignment_level": level,
                "submit_time": now if state == ReviewState.SUBMITTED else None,
                **(
                    {
                        "originality": 4,
                        "significance": 3,
                        "technical": 4,
                        "reference": 3,
                        "presentation": 4,
                        "match_topic": 5,
                        "recommendation": 4,
                        "contribution": "Good contribution to the field.",
                        "decision_reason": "Well written and technically sound.",
                        "comments": "Minor revisions suggested.",
                    }
                    if has_scores
                    else {}
                ),
            },
        )

        if created:
            logger.info(
                f"    Created review: <green>{paper_code}</> "
                f"by {reviewer.username} ({state})"
            )
        else:
            logger.info(
                f"    Review already exists: <yellow>{paper_code}</> "
                f"by {reviewer.username}"
            )

    paper = papers.filter(code="TP-002").first()
    if paper:
        Review.objects.get_or_create(
            paper=paper,
            reviewer=track_a_reviewer,
            state=ReviewState.DECLINED,
            defaults={
                "assigner": chair,
                "assignment_level": ReviewAssignmentLevel.TRACK,
            },
        )


def seed_registrations(
    users: dict[str, User],
    conference: Conference,
) -> None:
    logger.info("Seeding registrations...")

    author = users["author"]
    another_author = users["another-author"]

    author_type = AttendanceType.objects.get(
        conference=conference,
        display_name="Author",
    )
    regular_type = AttendanceType.objects.get(
        conference=conference,
        display_name="Regular Attendee",
    )

    accepted_paper = Paper.objects.filter(
        conference=conference,
        code="TP-004",
    ).first()

    registration_specs = [
        # (user, state, attendance_type, paper, title)
        (
            author,
            RegistrationState.CONFIRMED,
            author_type,
            accepted_paper,
            RegistrationTitle.DR,
        ),
        (author, RegistrationState.PENDING, regular_type, None, RegistrationTitle.DR),
        (
            another_author,
            RegistrationState.PENDING,
            regular_type,
            None,
            RegistrationTitle.MR,
        ),
        (
            another_author,
            RegistrationState.CANCELLED,
            regular_type,
            None,
            RegistrationTitle.MR,
        ),
    ]

    for user, state, attendance_type, paper, title in registration_specs:
        profile = user.profile
        _, created = Registration.objects.get_or_create(
            conference=conference,
            user=user,
            state=state,
            defaults={
                "attendance_type": attendance_type,
                "paper": paper,
                "title": title,
                "given_name": profile.given_name,
                "family_name": profile.family_name,
                "affiliation": profile.affiliation,
                "region_code": profile.region_code,
                "email": user.email,
                "phone": "+1-555-0100",
                "receipt_title": profile.affiliation,
            },
        )

        if created:
            logger.info(
                f"    Created registration: <green>{user.username}</> ({state})"
            )
        else:
            logger.info(
                f"    Registration already exists: <yellow>{user.username}</> ({state})"
            )


def seed_payments(conference: Conference) -> None:
    logger.info("Seeding payments...")

    # Get registrations to link payments to
    registrations = Registration.objects.filter(conference=conference)

    payment_specs = [
        # (reference, amount, currency, type, method, note, deleted)
        (
            "TXN-001",
            Decimal("500.00"),
            PaymentCurrency.USD,
            PaymentType.PAYMENT,
            PaymentMethod.CREDIT_CARD,
            "Online payment for registration",
            False,
        ),
        (
            "TXN-002",
            Decimal("350.00"),
            PaymentCurrency.USD,
            PaymentType.PAYMENT,
            PaymentMethod.WIRE_TRANSFER,
            "Wire transfer payment",
            False,
        ),
        (
            "TXN-003",
            Decimal("50.00"),
            PaymentCurrency.USD,
            PaymentType.REFUND,
            PaymentMethod.CREDIT_CARD,
            "Partial refund",
            False,
        ),
        (
            "TXN-004",
            Decimal(45000),
            PaymentCurrency.JPY,
            PaymentType.PAYMENT,
            PaymentMethod.CREDIT_CARD,
            "JPY payment",
            False,
        ),
        (
            "TXN-005",
            Decimal("400.00"),
            PaymentCurrency.EUR,
            PaymentType.PAYMENT,
            PaymentMethod.OTHER,
            "Cash payment at venue",
            False,
        ),
        (
            "TXN-DEL",
            Decimal("100.00"),
            PaymentCurrency.USD,
            PaymentType.PAYMENT,
            PaymentMethod.CREDIT_CARD,
            "Deleted payment example",
            True,
        ),
    ]

    now = timezone.now()
    confirmed_reg = registrations.filter(state=RegistrationState.CONFIRMED).first()
    pending_reg = registrations.filter(state=RegistrationState.PENDING).first()

    for (
        reference,
        amount,
        currency,
        payment_type,
        method,
        note,
        deleted,
    ) in payment_specs:
        payment, created = Payment.objects.get_or_create(
            conference=conference,
            reference=reference,
            defaults={
                "amount": amount,
                "currency": currency,
                "type": payment_type,
                "method": method,
                "note": note,
                "delete_time": now if deleted else None,
            },
        )

        if created:
            logger.info(
                f"    Created payment: <green>{reference}</> "
                f"({amount} {currency}, {payment_type})"
            )

            if payment_type == PaymentType.PAYMENT and confirmed_reg:
                PaymentItem.objects.create(
                    payment=payment,
                    registration=confirmed_reg,
                    amount=amount,
                    description="Registration fee",
                )
            elif payment_type == PaymentType.REFUND and pending_reg:
                PaymentItem.objects.create(
                    payment=payment,
                    registration=pending_reg,
                    amount=amount,
                    description="Refund for cancellation",
                )
        else:
            logger.info(f"    Payment already exists: <yellow>{reference}</>")


def seed_invitations(
    users: dict[str, User],
    conference: Conference,
    tracks: dict[str, Track],
) -> None:
    logger.info("Seeding invitations...")

    chair = users["conf-chair"]
    now = timezone.now()

    invitation_specs = [
        # (email, state, conf_roles, track_roles)
        # state: "pending", "accepted", "rejected"
        (
            "pending-reviewer@example.com",
            "pending",
            [ConferenceRole.REVIEWER],
            [],
        ),
        (
            "pending-track-chair@example.com",
            "pending",
            [],
            [("track-a", TrackRole.CHAIR)],
        ),
        (
            "rejected-invite@example.com",
            "rejected",
            [ConferenceRole.REVIEWER],
            [],
        ),
    ]

    for email, state, conf_roles, track_roles in invitation_specs:
        defaults = {
            "inviter": chair,
            "given_name": email.split("@")[0].replace("-", " ").title(),
            "family_name": "Invited",
            "affiliation": "Invited Institution",
            "region_code": "US",
        }

        if state == "rejected":
            defaults["reject_time"] = now

        invitation, created = Invitation.objects.get_or_create(
            conference=conference,
            invitee_email=email,
            defaults=defaults,
        )

        if created:
            logger.info(f"    Created invitation: <green>{email}</> ({state})")

            for conf_role in conf_roles:
                InvitationConferenceRoleEntry.objects.create(
                    invitation=invitation,
                    role=conf_role,
                )

            for track_key, track_role in track_roles:
                InvitationTrackRoleEntry.objects.create(
                    invitation=invitation,
                    track=tracks[track_key],
                    role=track_role,
                )
        else:
            logger.info(f"    Invitation already exists: <yellow>{email}</>")
