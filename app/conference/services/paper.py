from collections.abc import Collection
from typing import Literal, TypedDict

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from app.conference.models import Conference, Keyword, Paper, PaperAuthor, Track
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


class PaperService:
    @classmethod
    @transaction.atomic
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

        Raises:
            NoCodePoolError: If the track has no code pool configured.
        """
        code_pool = track.code_pool
        if not code_pool:
            raise NoCodePoolError("Track has no code pool configured.")

        code = code_pool.allocate_code()
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
            cls.set_paper_keywords(paper, keywords)
        if authors:
            cls.set_paper_authors(paper, authors)

        return paper

    @classmethod
    def update_paper(
        cls,
        *,
        paper: Paper,
        mode: Literal["author", "track_admin", "admin"] = "author",
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
                if paper.state != Paper.State.DRAFT:
                    raise PaperStateError(_("Paper must be in Draft state to update."))
            elif mode == "track_admin" and paper.state in Paper.State.decided():
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
                cls.set_paper_keywords(paper, keywords)

            if authors is not None:
                cls.set_paper_authors(paper, authors)

            return paper

    @classmethod
    def delete_paper(
        cls,
        *,
        paper: Paper,
        mode: Literal["author", "track_admin", "admin"] = "author",
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
                if paper.state not in (Paper.State.DRAFT, Paper.State.SUBMITTED):
                    raise PaperStateError(
                        _("Paper must be in Draft or Submitted state to delete.")
                    )
            elif mode == "track_admin" and paper.state in Paper.State.decided():
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
    def set_paper_keywords(cls, paper: Paper, keywords: Collection[Keyword]) -> None:
        """Replace all keywords on a paper."""
        paper.keywords.set(keywords)

    @classmethod
    def set_paper_authors(cls, paper: Paper, authors: Collection[AuthorData]) -> None:
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
