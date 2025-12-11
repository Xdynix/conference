import pytest
from django.db import IntegrityError
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    Conference,
    Paper,
    PaperAuthor,
    PaperDocument,
    PaperFinal,
    PaperSubmission,
    Track,
)
from app.conference.models.paper import (
    paper_document_path,
    paper_final_source_path,
    paper_final_viewable_path,
    paper_submission_path,
)
from app.core.models import User


@pytest.fixture
def user(faker: Faker) -> User:
    return User.objects.create_user(
        username=faker.user_name(),
        email=faker.email(),
    )


@pytest.fixture
def conference(faker: Faker) -> Conference:
    return Conference.objects.create(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
def track(conference: Conference, faker: Faker) -> Track:
    return Track.objects.create(
        conference=conference,
        display_name=faker.word(),
    )


@pytest.fixture
def paper(faker: Faker, user: User, conference: Conference, track: Track) -> Paper:
    return Paper.objects.create(
        conference=conference,
        track=track,
        code=faker.lexify(text="????-###"),
        owner=user,
        title=faker.sentence(),
    )


@pytest.mark.django_db
class TestPaperQuerySet:
    def test_active_excludes_deleted_papers(
        self,
        conference: Conference,
        track: Track,
        user: User,
        faker: Faker,
    ) -> None:
        active_paper = Paper.objects.create(
            conference=conference,
            track=track,
            code="ACTIVE-001",
            owner=user,
            title=faker.sentence(),
        )
        deleted_paper = Paper.objects.create(
            conference=conference,
            track=track,
            code="DELETED-001",
            owner=user,
            title=faker.sentence(),
            delete_time=timezone.now(),
        )

        active_papers = Paper.objects.active()

        assert active_papers.count() == 1
        assert active_paper in active_papers
        assert deleted_paper not in active_papers


@pytest.mark.django_db
class TestPaper:
    def test_str(self, paper: Paper) -> None:
        assert str(paper) == f"[{paper.track}] {paper.code}"

    def test_unique_code_within_conference(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        Paper.objects.create(
            conference=conference,
            track=track,
            code="DUPLICATE-001",
            owner=user,
            title=faker.sentence(),
        )

        with pytest.raises(IntegrityError):
            Paper.objects.create(
                conference=conference,
                track=track,
                code="DUPLICATE-001",
                owner=user,
                title=faker.sentence(),
            )

    def test_same_code_different_conference(
        self,
        faker: Faker,
        user: User,
    ) -> None:
        conference1 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        track1 = Track.objects.create(
            conference=conference1,
            display_name=faker.word(),
        )
        conference2 = Conference.objects.create(
            name=faker.slug(),
            display_name=faker.sentence(),
        )
        track2 = Track.objects.create(
            conference=conference2,
            display_name=faker.word(),
        )
        Paper.objects.create(
            conference=conference1,
            track=track1,
            code="SAME-001",
            owner=user,
            title=faker.sentence(),
        )
        Paper.objects.create(
            conference=conference2,
            track=track2,
            code="SAME-001",
            owner=user,
            title=faker.sentence(),
        )


@pytest.mark.django_db
class TestPaperAuthor:
    def test_str_with_both_names(self, paper: Paper) -> None:
        author = PaperAuthor.objects.create(
            paper=paper,
            given_name="Alice",
            family_name="Smith",
        )
        assert str(author) == "Alice Smith"

    def test_str_with_given_name_only(self, paper: Paper) -> None:
        author = PaperAuthor.objects.create(
            paper=paper,
            given_name="Alice",
        )
        assert str(author) == "Alice"

    def test_str_with_family_name_only(self, paper: Paper) -> None:
        author = PaperAuthor.objects.create(
            paper=paper,
            family_name="Smith",
        )
        assert str(author) == "Smith"

    def test_str_with_no_names(self, paper: Paper) -> None:
        author = PaperAuthor.objects.create(paper=paper)
        assert str(author) == ""

    def test_ordering(self, paper: Paper, faker: Faker) -> None:
        author3 = PaperAuthor.objects.create(
            paper=paper,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            ordering=2,
        )
        author1 = PaperAuthor.objects.create(
            paper=paper,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            ordering=0,
        )
        author2 = PaperAuthor.objects.create(
            paper=paper,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            ordering=1,
        )

        authors = list(PaperAuthor.objects.filter(paper=paper))
        assert authors == [author1, author2, author3]

    def test_unique_ordering_per_paper(self, paper: Paper, faker: Faker) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            ordering=0,
        )

        with pytest.raises(IntegrityError):
            PaperAuthor.objects.create(
                paper=paper,
                given_name=faker.first_name(),
                family_name=faker.last_name(),
                ordering=0,
            )

    def test_same_ordering_different_paper(
        self,
        conference: Conference,
        track: Track,
        user: User,
        faker: Faker,
    ) -> None:
        paper1 = Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-001",
            owner=user,
            title=faker.sentence(),
        )
        paper2 = Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-002",
            owner=user,
            title=faker.sentence(),
        )

        PaperAuthor.objects.create(
            paper=paper1,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            ordering=0,
        )
        PaperAuthor.objects.create(
            paper=paper2,
            given_name=faker.first_name(),
            family_name=faker.last_name(),
            ordering=0,
        )


@pytest.mark.django_db
class TestPaperSubmission:
    def test_str(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=1)
        assert str(submission) == f"{paper} rev1"

    def test_unique_revision_per_paper(self, paper: Paper) -> None:
        PaperSubmission.objects.create(paper=paper, revision=1, file="test.pdf")

        with pytest.raises(IntegrityError):
            PaperSubmission.objects.create(paper=paper, revision=1, file="test2.pdf")

    def test_same_revision_different_paper(
        self,
        conference: Conference,
        track: Track,
        user: User,
        faker: Faker,
    ) -> None:
        paper1 = Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-001",
            owner=user,
            title=faker.sentence(),
        )
        paper2 = Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-002",
            owner=user,
            title=faker.sentence(),
        )

        PaperSubmission.objects.create(paper=paper1, revision=1, file="test.pdf")
        PaperSubmission.objects.create(paper=paper2, revision=1, file="test.pdf")

    def test_ordering(self, paper: Paper) -> None:
        sub2 = PaperSubmission.objects.create(paper=paper, revision=2, file="test.pdf")
        sub1 = PaperSubmission.objects.create(paper=paper, revision=1, file="test.pdf")
        sub3 = PaperSubmission.objects.create(paper=paper, revision=3, file="test.pdf")

        submissions = list(PaperSubmission.objects.filter(paper=paper))
        assert submissions == [sub3, sub2, sub1]


@pytest.mark.django_db
class TestPaperSubmissionPath:
    def test_generates_path(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=1)
        path = paper_submission_path(submission, "manuscript.pdf")
        assert path == f"{paper.conference.name}/{paper.code}/submission-rev1.pdf"

    def test_lowercases_extension(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=2)
        path = paper_submission_path(submission, "document.PDF")
        assert path.endswith(".pdf")

    def test_truncates_long_extension(self, paper: Paper) -> None:
        submission = PaperSubmission(paper=paper, revision=1)
        path = paper_submission_path(submission, "file.very-long-extension")
        ext = path.split(".")[-1]
        assert len(ext) < 10


@pytest.mark.django_db
class TestPaperFinal:
    def test_str(self, paper: Paper) -> None:
        final = PaperFinal(paper=paper, revision=1)
        assert str(final) == f"{paper} final rev1"

    def test_unique_revision_per_paper(self, paper: Paper) -> None:
        PaperFinal.objects.create(paper=paper, revision=1, source_file="source.zip")

        with pytest.raises(IntegrityError):
            PaperFinal.objects.create(
                paper=paper,
                revision=1,
                source_file="source2.zip",
            )

    def test_same_revision_different_paper(
        self,
        conference: Conference,
        track: Track,
        user: User,
        faker: Faker,
    ) -> None:
        paper1 = Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-001",
            owner=user,
            title=faker.sentence(),
        )
        paper2 = Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-002",
            owner=user,
            title=faker.sentence(),
        )

        PaperFinal.objects.create(paper=paper1, revision=1, source_file="source.zip")
        PaperFinal.objects.create(paper=paper2, revision=1, source_file="source.zip")

    def test_ordering(self, paper: Paper) -> None:
        final2 = PaperFinal.objects.create(
            paper=paper,
            revision=2,
            source_file="source.zip",
        )
        final1 = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="source.zip",
        )
        final3 = PaperFinal.objects.create(
            paper=paper,
            revision=3,
            source_file="source.zip",
        )

        finals = list(PaperFinal.objects.filter(paper=paper))
        assert finals == [final3, final2, final1]

    def test_viewable_file_optional(self, paper: Paper) -> None:
        final = PaperFinal.objects.create(
            paper=paper,
            revision=1,
            source_file="source.zip",
        )
        assert not final.viewable_file


@pytest.mark.django_db
class TestPaperFinalPath:
    def test_source_path(self, paper: Paper) -> None:
        final = PaperFinal(paper=paper, revision=1)
        path = paper_final_source_path(final, "source.zip")
        assert path == f"{paper.conference.name}/{paper.code}/final-rev1-source.zip"

    def test_viewable_path(self, paper: Paper) -> None:
        final = PaperFinal(paper=paper, revision=1)
        path = paper_final_viewable_path(final, "paper.pdf")
        assert path == f"{paper.conference.name}/{paper.code}/final-rev1-viewable.pdf"

    def test_lowercases_extension(self, paper: Paper) -> None:
        final = PaperFinal(paper=paper, revision=1)
        source_path = paper_final_source_path(final, "source.ZIP")
        viewable_path = paper_final_viewable_path(final, "paper.PDF")
        assert source_path.endswith(".zip")
        assert viewable_path.endswith(".pdf")


@pytest.mark.django_db
class TestPaperDocument:
    def test_str_acceptance_letter(self, paper: Paper) -> None:
        doc = PaperDocument(
            paper=paper,
            type=PaperDocument.Type.ACCEPTANCE_LETTER,
            file="letter.pdf",
        )
        assert str(doc) == f"{paper} Acceptance Letter"

    def test_str_other(self, paper: Paper) -> None:
        doc = PaperDocument(paper=paper, type=PaperDocument.Type.OTHER, file="doc.pdf")
        assert str(doc) == f"{paper} Other"

    def test_multiple_documents_same_type(self, paper: Paper) -> None:
        PaperDocument.objects.create(
            paper=paper,
            type=PaperDocument.Type.OTHER,
            file="doc1.pdf",
        )
        PaperDocument.objects.create(
            paper=paper,
            type=PaperDocument.Type.OTHER,
            file="doc2.pdf",
        )
        assert PaperDocument.objects.filter(paper=paper).count() == 2


@pytest.mark.django_db
class TestPaperDocumentPath:
    def test_generates_path(self, paper: Paper) -> None:
        doc = PaperDocument(paper=paper, type=PaperDocument.Type.ACCEPTANCE_LETTER)
        path = paper_document_path(doc, "acceptance-letter.pdf")
        assert path == f"{paper.conference.name}/{paper.code}/doc-acceptance-letter.pdf"
