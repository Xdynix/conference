from collections.abc import Collection
from typing import Literal, TypedDict

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from loguru import logger

from app.conference.models import (
    Conference,
    Keyword,
    Paper,
    PaperAuthor,
    PaperDecision,
    PaperDecisionState,
    PaperLabel,
    PaperState,
    Track,
)
from app.core.models import GlobalRole, User
from app.infra.models import Mutex

from .access import ConferenceAccessService


class AuthorData(TypedDict, total=False):
    given_name: str
    family_name: str
    affiliation: str
    region_code: str
    email: str
    phone: str
    corresponding: bool


class NoCodePoolError(Exception):
    pass


class PaperStateError(Exception):
    pass


class PaperWithdrawnError(PaperStateError):
    pass


class PaperSubmissionError(Exception):
    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__(_("Paper submission validation failed."))


class PaperService:
    max_code_retries = 100

    @classmethod
    def create_paper(
        cls,
        *,
        track: Track,
        owner: User,
        title: str = "",
        abstract: str = "",
        contribution: str = "",
        keywords: Collection[Keyword] = (),
        authors: Collection[AuthorData] = (),
    ) -> Paper:
        """Create a new draft paper in the given track.

        The caller is responsible for verifying that:
        - The user has access to the conference and track.
        - The track enabled submissions (if applicable).

        If a code collision occurs (e.g., due to manual data entry that left the code
        pool sequence out of sync), the method automatically retries with the next
        available code.

        Raises:
            NoCodePoolError: If the track has no code pool configured.
        """
        code_pool = track.code_pool
        if not code_pool:
            raise NoCodePoolError("Track has no code pool configured.")

        for attempt in range(cls.max_code_retries):
            code = code_pool.allocate_code()
            try:
                with transaction.atomic():
                    paper = Paper.objects.create(
                        conference_id=track.conference_id,
                        track=track,
                        code=code,
                        owner=owner,
                        title=title,
                        abstract=abstract,
                        contribution=contribution,
                    )
                    if keywords:
                        cls._set_paper_keywords(paper, keywords)
                    if authors:
                        cls._set_paper_authors(paper, authors)
                    return paper
            except IntegrityError:
                is_last_attempt = attempt >= cls.max_code_retries - 1
                is_code_collision = Paper.objects.filter(
                    conference_id=track.conference_id,
                    code=code,
                ).exists()
                if is_last_attempt or not is_code_collision:
                    raise
                logger.warning(
                    "Paper code collision detected, retrying with next code.",
                    code=code,
                    conference_id=track.conference_id,
                    attempt=attempt + 1,
                )

        raise AssertionError(
            "Unreachable: loop always returns or raises."
        )  # pragma: no cover

    @classmethod
    def update_paper(
        cls,
        *,
        paper: Paper,
        mode: Literal["author", "track_admin", "admin"],
        title: str | None = None,
        abstract: str | None = None,
        contribution: str | None = None,
        keywords: Collection[Keyword] | None = None,
        authors: Collection[AuthorData] | None = None,
    ) -> Paper:
        """Update paper metadata, authors, and keywords.

        The caller is responsible for verifying that the user has permission to update
        this paper.

        Args:
            paper: The paper to update.
            mode: Controls state restrictions. ``"author"`` allows only Draft
                state. ``"track_admin"`` allows Draft, Submitted, and Under
                Review. ``"admin"`` allows any state.
            title: Title of the paper.
            abstract: Abstract of the paper.
            contribution: Contribution statement of the paper.
            keywords: Keywords of the paper.
            authors: Authors of the paper.

        Raises:
            Paper.DoesNotExist: If the paper, its conference, or its track has
                been deleted or deactivated.
            PaperStateError: If the paper state is not allowed for the given mode.
            PaperWithdrawnError: If the paper has been withdrawn.
        """
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper = Paper.objects.active().get(pk=paper.pk)

            if paper.withdraw_time is not None:
                raise PaperWithdrawnError(_("Withdrawn papers cannot be updated."))

            if mode == "author":
                if paper.state != PaperState.DRAFT:
                    raise PaperStateError(_("Paper must be in Draft state to update."))
            elif mode == "track_admin" and paper.state in PaperState.decided():
                raise PaperStateError(
                    _("Only conference admins can update papers after decision.")
                )

            update_fields = []
            if title is not None:
                paper.title = title
                update_fields.append("title")
            if abstract is not None:
                paper.abstract = abstract
                update_fields.append("abstract")
            if contribution is not None:
                paper.contribution = contribution
                update_fields.append("contribution")

            if update_fields:
                paper.save(update_fields=[*update_fields, "update_time"])

            if keywords is not None:
                cls._set_paper_keywords(paper, keywords)

            if authors is not None:
                cls._set_paper_authors(paper, authors)

            return paper

    @classmethod
    def delete_paper(
        cls,
        *,
        paper: Paper,
        mode: Literal["author", "track_admin", "admin"],
    ) -> Paper:
        """Soft delete a paper by setting ``delete_time``.

        The caller is responsible for verifying that the user has permission to delete
        this paper.

        Args:
            paper: The paper to delete.
            mode: Controls state restrictions. ``"author"`` allows only Draft or
                Submitted state. ``"track_admin"`` allows Draft, Submitted, and
                Under Review. ``"admin"`` allows any state.

        Raises:
            Paper.DoesNotExist: If the paper, its conference, or its track has
                been deleted or deactivated.
            PaperStateError: If the paper state is not allowed for the given mode.
            PaperWithdrawnError: If the paper has been withdrawn.
        """
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper = Paper.objects.active().get(pk=paper.pk)

            if paper.withdraw_time is not None:
                raise PaperWithdrawnError(_("Withdrawn papers cannot be deleted."))

            if mode == "author":
                if paper.state not in (PaperState.DRAFT, PaperState.SUBMITTED):
                    raise PaperStateError(
                        _("Paper must be in Draft or Submitted state to delete.")
                    )
            elif mode == "track_admin" and paper.state in PaperState.decided():
                raise PaperStateError(
                    _(
                        "Track admins can only delete papers in Draft, Submitted, "
                        "or Under Review state."
                    )
                )

            paper.delete_time = timezone.now()
            paper.save(update_fields=["delete_time", "update_time"])

            return paper

    @classmethod
    def submit_paper(cls, paper: Paper, *, strict: bool = True) -> Paper:
        """Submit a paper for review.

        Validates required fields and transitions the paper from Draft to
        Submitted state.

        Args:
            paper: The paper to submit.
            strict: If ``True`` (default), validates all required fields including
                abstract, contribution, keywords, submission file, and authors.
                If ``False``, only validates title (for admin bypass).

        Raises:
            Paper.DoesNotExist: If the paper, its conference, or its track has been
                deleted or deactivated.
            PaperStateError: If the paper is not in Draft state.
            PaperWithdrawnError: If the paper has been withdrawn.
            PaperSubmissionError: If the paper fails field validation. The exception
                contains a list of error dictionaries.
        """
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper = Paper.objects.active().prefetch_related("authors").get(pk=paper.pk)

            if paper.withdraw_time is not None:
                raise PaperWithdrawnError(_("Withdrawn papers cannot be submitted."))
            if paper.state != PaperState.DRAFT:
                raise PaperStateError(_("Paper must be in Draft state to submit."))

            errors: list[dict[str, str]] = []
            if not paper.title:
                errors.append({"title": _("Title is required.")})

            if strict:
                if not paper.abstract:
                    errors.append({"abstract": _("Abstract is required.")})
                if not paper.contribution:
                    errors.append(
                        {"contribution": _("Contribution statement is required.")}
                    )

                if not paper.keywords.exists():
                    errors.append({"keywords": _("At least one keyword is required.")})
                if not paper.submissions.exists():
                    errors.append({"submissions": _("A submission file is required.")})

                authors = list(paper.authors.all())
                if not authors:
                    errors.append({"authors": _("At least one author is required.")})
                else:
                    corresponding_count = sum(1 for a in authors if a.corresponding)
                    if corresponding_count == 0:
                        errors.append(
                            {
                                "authors": _(
                                    "One author must be marked as corresponding."
                                )
                            }
                        )
                    elif corresponding_count > 1:
                        errors.append(
                            {
                                "authors": _(
                                    "Only one author can be marked as corresponding."
                                )
                            }
                        )

                    for idx, author in enumerate(authors, start=1):
                        missing_fields = []
                        if not author.given_name:
                            missing_fields.append("given name")
                        if not author.family_name:
                            missing_fields.append("family name")
                        if not author.affiliation:
                            missing_fields.append("affiliation")
                        if not author.region_code:
                            missing_fields.append("region")
                        if not author.email:
                            missing_fields.append("email")

                        if missing_fields:
                            message = _("Missing required fields: {fields}.").format(
                                fields=", ".join(missing_fields)
                            )
                            errors.append({f"authors[{idx}]": message})

            if errors:
                raise PaperSubmissionError(errors)

            paper.state = PaperState.SUBMITTED
            paper.submit_time = timezone.now()
            paper.save(update_fields=["state", "submit_time", "update_time"])

            return paper

    @classmethod
    def unsubmit_paper(cls, paper: Paper) -> Paper:
        """Unsubmit a paper to allow further editing.

        Transitions the paper from Submitted back to Draft state.

        Raises:
            Paper.DoesNotExist: If the paper, its conference, or its track has
                been deleted or deactivated.
            PaperStateError: If the paper is not in Submitted state.
            PaperWithdrawnError: If the paper has been withdrawn.
        """
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper = Paper.objects.active().get(pk=paper.pk)

            if paper.withdraw_time is not None:
                raise PaperWithdrawnError(_("Withdrawn papers cannot be unsubmitted."))
            if paper.state != PaperState.SUBMITTED:
                raise PaperStateError(
                    _("Paper must be in Submitted state to unsubmit.")
                )

            paper.state = PaperState.DRAFT
            paper.submit_time = None
            paper.save(update_fields=["state", "submit_time", "update_time"])

            return paper

    @classmethod
    def withdraw_paper(cls, paper: Paper) -> Paper:
        """Withdraw a paper from consideration.

        Marks the paper as withdrawn by setting ``withdraw_time``. Withdrawal can happen
        from any state and is final.

        Raises:
            Paper.DoesNotExist: If the paper, its conference, or its track has
                been deleted or deactivated.
            PaperWithdrawnError: If the paper has already been withdrawn.
        """
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper = Paper.objects.active().get(pk=paper.pk)

            if paper.withdraw_time is not None:
                raise PaperWithdrawnError(_("Paper has already been withdrawn."))

            paper.withdraw_time = timezone.now()
            paper.save(update_fields=["withdraw_time", "update_time"])

            return paper

    @classmethod
    def decide_paper(
        cls,
        *,
        paper: Paper,
        decider: User,
        state: PaperState,
        note: str = "",
    ) -> Paper:
        """Make a decision on a paper.

        Updates the paper state and creates an audit record. Papers in any state except
        Draft can be decided.

        Raises:
            Paper.DoesNotExist: If the paper has been deleted or deactivated.
            PaperStateError: If the paper is in Draft state.
            PaperWithdrawnError: If the paper has been withdrawn.
            ValueError: If the state is not a valid decision state.
        """
        if state not in PaperState.decided():
            raise ValueError(f"Invalid decision state: {state}.")

        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper = Paper.objects.active().get(pk=paper.pk)

            if paper.withdraw_time is not None:
                raise PaperWithdrawnError(_("Withdrawn papers cannot be decided."))
            if paper.state == PaperState.DRAFT:
                raise PaperStateError(_("Draft papers cannot be decided."))

            paper.state = state
            paper.save(update_fields=["state", "update_time"])

            PaperDecision.objects.create(
                paper=paper,
                decider=decider,
                state=PaperDecisionState(state),
                note=note,
            )

            return paper

    @classmethod
    def set_paper_labels(cls, paper: Paper, **labels: str) -> None:
        """Replace all labels on a paper."""
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            paper.labels.all().delete()
            label_objects = [
                PaperLabel(paper=paper, key=key, value=value)
                for key, value in labels.items()
            ]
            if label_objects:
                PaperLabel.objects.bulk_create(label_objects)

    @classmethod
    async def visible_papers(
        cls,
        conference: Conference,
        user: User,
        global_readable: Collection[GlobalRole] = (
            GlobalRole.ADMIN,
            GlobalRole.READ_ALL,
        ),
    ) -> QuerySet[Paper]:
        """Return papers for the conference visible to the user.

        Visibility rules:

        - Superusers and users with ADMIN/READ_ALL global roles see all papers.
        - Conference admins (chairs and secretaries) see all papers.
        - Track admins see only papers in tracks they administer.
        - Other users see no papers.
        """
        papers = conference.papers.active()

        ctx = await ConferenceAccessService.context(
            conference=conference,
            user=user,
            global_roles=global_readable,
        )

        if ctx.has_full_conference_scope:
            return papers

        if not ctx.administered_track_ids:
            return papers.none()

        return papers.filter(track_id__in=ctx.administered_track_ids)

    @classmethod
    def _set_paper_keywords(cls, paper: Paper, keywords: Collection[Keyword]) -> None:
        """Replace all keywords on a paper."""
        paper.keywords.set(keywords)

    @classmethod
    def _set_paper_authors(cls, paper: Paper, authors: Collection[AuthorData]) -> None:
        """Replace all authors on a paper.

        Authors are assigned ordering based on their position in the collection.
        """
        paper.authors.all().delete()
        author_objects = [
            PaperAuthor(
                paper=paper,
                ordering=idx,
                given_name=author.get("given_name", ""),
                family_name=author.get("family_name", ""),
                affiliation=author.get("affiliation", ""),
                region_code=author.get("region_code", ""),
                email=author.get("email", ""),
                phone=author.get("phone", ""),
                corresponding=author.get("corresponding", False),
            )
            for idx, author in enumerate(authors)
        ]
        if author_objects:
            PaperAuthor.objects.bulk_create(author_objects)
