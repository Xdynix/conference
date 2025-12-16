from collections.abc import Collection
from typing import TypedDict

from django.db import transaction
from django.db.models import QuerySet
from django.utils.translation import gettext as _

from app.conference.models import Conference, Keyword, Paper, PaperAuthor, Track
from app.core.models import GlobalRole, User

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


class PaperWithdrawnError(Exception):
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
    @transaction.atomic
    def update_paper(
        cls,
        *,
        paper: Paper,
        title: str | None = None,
        abstract: str | None = None,
        contribution: str | None = None,
        keywords: Collection[Keyword] | None = None,
        authors: Collection[AuthorData] | None = None,
    ) -> Paper:
        """Update paper metadata, authors, and keywords.

        The caller is responsible for verifying that:
        - The user has permission to update this paper.
        - The paper state allows updates (if applicable).

        Raises:
            PaperWithdrawnError: If the paper has been withdrawn.
        """
        if paper.withdraw_time is not None:
            raise PaperWithdrawnError(_("Withdrawn papers cannot be updated."))

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
            paper.save(update_fields=update_fields)

        if keywords is not None:
            cls.set_paper_keywords(paper, keywords)

        if authors is not None:
            cls.set_paper_authors(paper, authors)

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
