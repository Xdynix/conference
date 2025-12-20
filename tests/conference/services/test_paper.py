import pytest
from django.utils import timezone
from faker import Faker

from app.conference.models import (
    CodePool,
    Conference,
    ConferenceRole,
    ConferenceRoleAssignment,
    Keyword,
    Paper,
    PaperAuthor,
    Track,
    TrackRole,
    TrackRoleAssignment,
)
from app.conference.services import PaperService
from app.conference.services.paper import (
    AuthorData,
    NoCodePoolError,
    PaperWithdrawnError,
)
from app.core.models import User
from tests.helpers import a_update_object, update_object


@pytest.fixture
def code_pool(conference: Conference) -> CodePool:
    return CodePool.objects.create(
        conference=conference,
        name="Main Pool",
        prefix="TEST-",
    )


@pytest.fixture
def track_with_pool(faker: Faker, conference: Conference, code_pool: CodePool) -> Track:
    return Track.objects.create(
        conference=conference,
        code_pool=code_pool,
        display_name=faker.word(),
    )


@pytest.mark.django_db
class TestPaperServiceCreatePaper:
    def test_happy_path(
        self,
        user: User,
        conference: Conference,
        track_with_pool: Track,
    ) -> None:
        paper = PaperService.create_paper(
            track=track_with_pool,
            owner=user,
            title="Test Paper",
            abstract="Test abstract",
            contribution="Test contribution",
        )

        db_paper = Paper.objects.get(pk=paper.pk)
        assert paper == db_paper
        assert paper.conference == db_paper.conference == conference
        assert paper.track == db_paper.track == track_with_pool
        assert paper.owner == db_paper.owner == user
        assert paper.title == db_paper.title == "Test Paper"
        assert paper.abstract == db_paper.abstract == "Test abstract"
        assert paper.contribution == db_paper.contribution == "Test contribution"
        assert paper.state == db_paper.state == Paper.State.DRAFT
        assert paper.code == db_paper.code == "TEST-001"

    def test_generates_sequential_codes(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        paper1 = PaperService.create_paper(track=track_with_pool, owner=user)
        paper2 = PaperService.create_paper(track=track_with_pool, owner=user)
        paper3 = PaperService.create_paper(track=track_with_pool, owner=user)

        assert paper1.code == "TEST-001"
        assert paper2.code == "TEST-002"
        assert paper3.code == "TEST-003"

    def test_defaults_to_empty_strings(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        paper = PaperService.create_paper(track=track_with_pool, owner=user)

        assert paper.title == ""
        assert paper.abstract == ""
        assert paper.contribution == ""

    def test_raises_when_track_has_no_code_pool(
        self,
        user: User,
        track: Track,
    ) -> None:
        with pytest.raises(NoCodePoolError):
            PaperService.create_paper(track=track, owner=user)

        assert not Paper.objects.exists()

    def test_with_keywords(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        kw1 = Keyword.objects.create(text="Keyword 1")
        kw2 = Keyword.objects.create(text="Keyword 2")

        paper = PaperService.create_paper(
            track=track_with_pool,
            owner=user,
            keywords=[kw1, kw2],
        )

        assert set(paper.keywords.all()) == {kw1, kw2}

    def test_with_authors(
        self,
        user: User,
        track_with_pool: Track,
    ) -> None:
        authors: list[AuthorData] = [
            {
                "given_name": "Alice",
                "family_name": "Smith",
                "email": "alice@example.com",
                "corresponding": True,
            },
            {
                "given_name": "Bob",
                "family_name": "Jones",
                "affiliation": "University",
            },
        ]

        paper = PaperService.create_paper(
            track=track_with_pool,
            owner=user,
            authors=authors,
        )

        [author0, author1] = list(paper.authors.all())

        assert author0.given_name == "Alice"
        assert author0.family_name == "Smith"
        assert author0.email == "alice@example.com"
        assert author0.corresponding is True
        assert author0.ordering == 0

        assert author1.given_name == "Bob"
        assert author1.family_name == "Jones"
        assert author1.affiliation == "University"
        assert author1.corresponding is False
        assert author1.ordering == 1


@pytest.mark.django_db
class TestPaperServiceUpdatePaper:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Original Title",
            abstract="Original abstract",
            contribution="Original contribution",
        )

    def test_happy_path(self, paper: Paper) -> None:
        kw1 = Keyword.objects.create(text="Keyword 1")
        kw2 = Keyword.objects.create(text="Keyword 2")
        authors: list[AuthorData] = [
            {"given_name": "Alice", "family_name": "Smith"},
            {"given_name": "Bob", "family_name": "Jones"},
        ]

        updated = PaperService.update_paper(
            paper=paper,
            title="Updated Title",
            abstract="Updated abstract",
            contribution="Updated contribution",
            keywords=[kw1, kw2],
            authors=authors,
        )

        db_updated = Paper.objects.get(pk=paper.pk)
        assert updated == db_updated
        assert updated.title == db_updated.title == "Updated Title"
        assert updated.abstract == db_updated.abstract == "Updated abstract"
        assert updated.contribution == db_updated.contribution == "Updated contribution"
        assert set(updated.keywords.all()) == {kw1, kw2}
        assert updated.authors.count() == 2

    def test_update_title_only(self, paper: Paper) -> None:
        PaperService.update_paper(paper=paper, title="New Title")

        paper.refresh_from_db()
        assert paper.title == "New Title"
        assert paper.abstract == "Original abstract"
        assert paper.contribution == "Original contribution"

    def test_update_abstract_only(self, paper: Paper) -> None:
        PaperService.update_paper(paper=paper, abstract="New abstract")

        paper.refresh_from_db()
        assert paper.title == "Original Title"
        assert paper.abstract == "New abstract"
        assert paper.contribution == "Original contribution"

    def test_update_contribution_only(self, paper: Paper) -> None:
        PaperService.update_paper(paper=paper, contribution="New contribution")

        paper.refresh_from_db()
        assert paper.title == "Original Title"
        assert paper.abstract == "Original abstract"
        assert paper.contribution == "New contribution"

    def test_set_fields_to_empty_string(self, paper: Paper) -> None:
        PaperService.update_paper(
            paper=paper,
            title="",
            abstract="",
            contribution="",
        )

        paper.refresh_from_db()
        assert paper.title == ""
        assert paper.abstract == ""
        assert paper.contribution == ""

    def test_update_keywords_replaces_all(self, paper: Paper) -> None:
        old_kw = Keyword.objects.create(text="Old Keyword")
        new_kw1 = Keyword.objects.create(text="New Keyword 1")
        new_kw2 = Keyword.objects.create(text="New Keyword 2")
        paper.keywords.add(old_kw)

        PaperService.update_paper(paper=paper, keywords=[new_kw1, new_kw2])

        assert set(paper.keywords.all()) == {new_kw1, new_kw2}

    def test_update_keywords_clears_with_empty_collection(self, paper: Paper) -> None:
        kw = Keyword.objects.create(text="Keyword")
        paper.keywords.add(kw)

        PaperService.update_paper(paper=paper, keywords=[])

        assert not paper.keywords.exists()

    def test_omit_keywords_keeps_existing(self, paper: Paper) -> None:
        kw = Keyword.objects.create(text="Keyword")
        paper.keywords.add(kw)

        PaperService.update_paper(paper=paper, title="New Title")

        assert list(paper.keywords.all()) == [kw]

    def test_update_authors_replaces_all(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Old",
            family_name="Author",
        )
        new_authors: list[AuthorData] = [
            {"given_name": "Alice", "family_name": "Smith"},
            {"given_name": "Bob", "family_name": "Jones"},
        ]

        PaperService.update_paper(paper=paper, authors=new_authors)

        [author0, author1] = list(paper.authors.all())
        assert author0.given_name == "Alice"
        assert author0.ordering == 0
        assert author1.given_name == "Bob"
        assert author1.ordering == 1

    def test_update_authors_clears_with_empty_collection(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Existing",
            family_name="Author",
        )

        PaperService.update_paper(paper=paper, authors=[])

        assert not paper.authors.exists()

    def test_raises_when_paper_is_withdrawn(self, paper: Paper) -> None:
        update_object(paper, withdraw_time=timezone.now())

        with pytest.raises(PaperWithdrawnError) as exc_info:
            PaperService.update_paper(paper=paper, title="Should fail")

        assert str(exc_info.value) == "Withdrawn papers cannot be updated."

        paper.refresh_from_db()
        assert paper.title == "Original Title"


@pytest.mark.django_db
class TestPaperServiceSetPaperKeywords:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
        )

    def test_sets_keywords(self, paper: Paper) -> None:
        kw1 = Keyword.objects.create(text="Keyword 1")
        kw2 = Keyword.objects.create(text="Keyword 2")

        PaperService.set_paper_keywords(paper, [kw1, kw2])

        assert set(paper.keywords.all()) == {kw1, kw2}

    def test_replaces_existing_keywords(self, paper: Paper) -> None:
        old_kw = Keyword.objects.create(text="Old Keyword")
        new_kw = Keyword.objects.create(text="New Keyword")
        paper.keywords.add(old_kw)

        PaperService.set_paper_keywords(paper, [new_kw])

        assert list(paper.keywords.all()) == [new_kw]

    def test_clears_keywords_with_empty_collection(self, paper: Paper) -> None:
        kw = Keyword.objects.create(text="Keyword")
        paper.keywords.add(kw)

        PaperService.set_paper_keywords(paper, [])

        assert not paper.keywords.exists()


@pytest.mark.django_db
class TestPaperServiceSetPaperAuthors:
    @pytest.fixture
    def paper(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
        )

    def test_sets_authors_with_ordering(self, paper: Paper) -> None:
        authors: list[AuthorData] = [
            {"given_name": "First", "family_name": "Author"},
            {"given_name": "Second", "family_name": "Author"},
            {"given_name": "Third", "family_name": "Author"},
        ]

        PaperService.set_paper_authors(paper, authors)

        db_authors = list(paper.authors.order_by("ordering"))
        assert len(db_authors) == 3
        assert db_authors[0].given_name == "First"
        assert db_authors[0].ordering == 0
        assert db_authors[1].given_name == "Second"
        assert db_authors[1].ordering == 1
        assert db_authors[2].given_name == "Third"
        assert db_authors[2].ordering == 2

    def test_sets_all_author_fields(self, paper: Paper) -> None:
        authors: list[AuthorData] = [
            {
                "given_name": "Alice",
                "family_name": "Smith",
                "affiliation": "MIT",
                "region_code": "US",
                "email": "alice@mit.edu",
                "phone": "+1234567890",
                "corresponding": True,
            },
        ]

        PaperService.set_paper_authors(paper, authors)

        author = paper.authors.get()
        assert author.given_name == "Alice"
        assert author.family_name == "Smith"
        assert author.affiliation == "MIT"
        assert author.region_code == "US"
        assert author.email == "alice@mit.edu"
        assert author.phone == "+1234567890"
        assert author.corresponding is True

    def test_defaults_missing_fields(self, paper: Paper) -> None:
        authors: list[AuthorData] = [{"given_name": "Alice"}]

        PaperService.set_paper_authors(paper, authors)

        author = paper.authors.get()
        assert author.given_name == "Alice"
        assert author.family_name == ""
        assert author.affiliation == ""
        assert author.region_code == ""
        assert author.email == ""
        assert author.phone == ""
        assert author.corresponding is False

    def test_replaces_existing_authors(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Old",
            family_name="Author",
        )
        authors: list[AuthorData] = [{"given_name": "New", "family_name": "Author"}]

        PaperService.set_paper_authors(paper, authors)

        assert paper.authors.count() == 1
        assert paper.authors.get().given_name == "New"

    def test_clears_authors_with_empty_collection(self, paper: Paper) -> None:
        PaperAuthor.objects.create(
            paper=paper,
            ordering=0,
            given_name="Existing",
            family_name="Author",
        )

        PaperService.set_paper_authors(paper, [])

        assert not paper.authors.exists()


@pytest.mark.django_db(transaction=True)
class TestPaperServiceVisiblePapers:
    async def test_superuser_sees_all_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await a_update_object(user, is_superuser=True)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper]

    async def test_global_admin_sees_all_papers(
        self,
        global_admin: User,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

        qs = await PaperService.visible_papers(conference, global_admin)
        papers = [p async for p in qs]

        assert papers == [paper]

    async def test_global_read_all_sees_all_papers(
        self,
        global_read_all: User,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

        qs = await PaperService.visible_papers(conference, global_read_all)
        papers = [p async for p in qs]

        assert papers == [paper]

    @pytest.mark.parametrize("conference_role", ConferenceRole.admins())
    async def test_conference_admin_sees_all_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
        conference_role: ConferenceRole,
    ) -> None:
        paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=conference_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper]

    @pytest.mark.parametrize("track_role", TrackRole.admins())
    async def test_track_admin_sees_only_papers_in_their_track(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
        track_role: TrackRole,
    ) -> None:
        other_track = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        paper_in_track = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Paper in Track",
        )
        await Paper.objects.acreate(
            conference=conference,
            track=other_track,
            owner=user,
            code="PAPER-002",
            title="Paper in Other Track",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=track_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [paper_in_track]

    async def test_track_admin_sees_papers_from_multiple_administered_tracks(
        self,
        faker: Faker,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        track_b = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        track_c = await Track.objects.acreate(
            conference=conference,
            display_name=faker.word(),
        )
        paper_a = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-A",
            title="Paper A",
        )
        paper_b = await Paper.objects.acreate(
            conference=conference,
            track=track_b,
            owner=user,
            code="PAPER-B",
            title="Paper B",
        )
        await Paper.objects.acreate(
            conference=conference,
            track=track_c,
            owner=user,
            code="PAPER-C",
            title="Paper C",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )
        await TrackRoleAssignment.objects.acreate(
            track=track_b,
            user=user,
            role=TrackRole.SECRETARY,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs.order_by("code")]

        assert papers == [paper_a, paper_b]

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in TrackRole if role not in TrackRole.admins()],
    )
    async def test_track_non_admin_role_sees_no_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
        non_admin_role: TrackRole,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=non_admin_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    @pytest.mark.parametrize(
        "non_admin_role",
        [role for role in ConferenceRole if role not in ConferenceRole.admins()],
    )
    async def test_conference_non_admin_role_sees_no_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
        non_admin_role: ConferenceRole,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await ConferenceRoleAssignment.objects.acreate(
            conference=conference,
            user=user,
            role=non_admin_role,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    async def test_user_without_roles_sees_no_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    async def test_excludes_deleted_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        active_paper = await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="ACTIVE-001",
            title="Active Paper",
        )
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="DELETED-001",
            title="Deleted Paper",
            delete_time=timezone.now(),
        )
        await a_update_object(user, is_superuser=True)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == [active_paper]

    async def test_excludes_inactive_conference_papers(
        self,
        global_admin: User,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await a_update_object(conference, active=False)

        qs = await PaperService.visible_papers(conference, global_admin)
        papers = [p async for p in qs]

        assert papers == []

    async def test_excludes_inactive_track_papers(
        self,
        global_admin: User,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await a_update_object(track, active=False)

        qs = await PaperService.visible_papers(conference, global_admin)
        papers = [p async for p in qs]

        assert papers == []

    async def test_inactive_track_does_not_grant_visibility(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        await Paper.objects.acreate(
            conference=conference,
            track=track,
            owner=user,
            code="PAPER-001",
            title="Test Paper",
        )
        await a_update_object(track, active=False)
        await TrackRoleAssignment.objects.acreate(
            track=track,
            user=user,
            role=TrackRole.CHAIR,
        )

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []

    async def test_returns_empty_when_no_papers(
        self,
        user: User,
        conference: Conference,
    ) -> None:
        await a_update_object(user, is_superuser=True)

        qs = await PaperService.visible_papers(conference, user)
        papers = [p async for p in qs]

        assert papers == []
