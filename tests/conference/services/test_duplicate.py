from datetime import timedelta

import pytest
from django.utils import timezone

from app.conference.models import (
    Conference,
    DuplicateMatch,
    DuplicateMatchType,
    DuplicateReport,
    DuplicateReportState,
    Paper,
    Track,
)
from app.conference.services.duplicate import (
    DuplicatePaperRow,
    DuplicateService,
    MatchPair,
    match_file_hash,
    match_title_similarity,
)
from app.core.models import User
from tests.helpers import update_object


def row(
    pk: int,
    title: str = "",
    *,
    submission_sha256: str | None = None,
    final_source_sha256: str | None = None,
    final_viewable_sha256: str | None = None,
) -> DuplicatePaperRow:
    return DuplicatePaperRow(
        pk=pk,
        title=title,
        submission_sha256=submission_sha256,
        final_source_sha256=final_source_sha256,
        final_viewable_sha256=final_viewable_sha256,
    )


class TestMatchFileHash:
    def test_shared_submission_hash(self) -> None:
        papers = [
            row(1, submission_sha256="aaa"),
            row(2, submission_sha256="aaa"),
        ]
        result = match_file_hash(papers)
        assert result == [MatchPair(1, 2, 1.0)]

    def test_shared_final_source_hash(self) -> None:
        papers = [
            row(1, final_source_sha256="bbb"),
            row(2, final_source_sha256="bbb"),
        ]
        result = match_file_hash(papers)
        assert result == [MatchPair(1, 2, 1.0)]

    def test_shared_final_viewable_hash(self) -> None:
        papers = [
            row(1, final_viewable_sha256="ccc"),
            row(2, final_viewable_sha256="ccc"),
        ]
        result = match_file_hash(papers)
        assert result == [MatchPair(1, 2, 1.0)]

    def test_multiple_shared_hashes_deduped(self) -> None:
        papers = [
            row(1, submission_sha256="aaa", final_source_sha256="bbb"),
            row(2, submission_sha256="aaa", final_source_sha256="bbb"),
        ]
        result = match_file_hash(papers)
        assert result == [MatchPair(1, 2, 1.0)]

    def test_three_papers_sharing_hash(self) -> None:
        papers = [
            row(1, submission_sha256="aaa"),
            row(2, submission_sha256="aaa"),
            row(3, submission_sha256="aaa"),
        ]
        result = match_file_hash(papers)
        assert sorted(result) == [
            MatchPair(1, 2, 1.0),
            MatchPair(1, 3, 1.0),
            MatchPair(2, 3, 1.0),
        ]

    def test_no_shared_hashes(self) -> None:
        papers = [
            row(1, submission_sha256="aaa"),
            row(2, submission_sha256="bbb"),
        ]
        assert match_file_hash(papers) == []

    def test_all_none_hashes(self) -> None:
        papers = [row(1), row(2)]
        assert match_file_hash(papers) == []

    def test_pair_ordering(self) -> None:
        papers = [
            row(10, submission_sha256="aaa"),
            row(5, submission_sha256="aaa"),
        ]
        result = match_file_hash(papers)
        assert result == [MatchPair(5, 10, 1.0)]


class TestMatchTitleSimilarity:
    def test_identical_titles(self) -> None:
        papers = [
            row(1, "Machine Learning in Healthcare"),
            row(2, "Machine Learning in Healthcare"),
        ]
        result = match_title_similarity(papers, threshold=0.6)
        assert len(result) == 1
        assert result[0].score == 1.0

    def test_completely_different_titles(self) -> None:
        papers = [
            row(1, "Machine Learning in Healthcare"),
            row(2, "Quantum Physics Experiments"),
        ]
        assert match_title_similarity(papers, threshold=0.6) == []

    def test_threshold_boundary(self) -> None:
        papers = [
            row(1, "Deep Learning for Image Recognition"),
            row(2, "Deep Learning for Image Classification"),
        ]
        score = match_title_similarity(papers, threshold=0.0)[0].score
        # The pair should be excluded when the threshold is above the score.
        assert match_title_similarity(papers, threshold=score) != []
        assert match_title_similarity(papers, threshold=score + 0.01) == []

    def test_pair_ordering(self) -> None:
        papers = [
            row(10, "Same Title"),
            row(5, "Same Title"),
        ]
        result = match_title_similarity(papers, threshold=0.6)
        assert result[0].paper_a_id == 5
        assert result[0].paper_b_id == 10


@pytest.mark.django_db
class TestDuplicateServiceScan:
    @pytest.fixture
    def paper_a(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-001",
            owner=user,
            title="Deep Learning for Image Recognition",
        )

    @pytest.fixture
    def paper_b(self, user: User, conference: Conference, track: Track) -> Paper:
        return Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-002",
            owner=user,
            title="Quantum Computing Algorithms",
        )

    def test_file_hash_match(self, paper_a: Paper, paper_b: Paper) -> None:
        paper_a.submissions.create(revision=1, file="paper.pdf", sha256="aaa")
        paper_b.submissions.create(revision=1, file="paper.pdf", sha256="aaa")

        report = DuplicateService.scan()

        assert report is not None
        assert report.state == DuplicateReportState.SUCCESS

        [match] = report.matches.filter(match_type=DuplicateMatchType.FILE_HASH)
        assert match.score == 1.0

    def test_title_similarity_match(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-A",
            owner=user,
            title="Deep Learning for Image Recognition",
        )
        Paper.objects.create(
            conference=conference,
            track=track,
            code="PAPER-B",
            owner=user,
            title="Deep Learning for Image Recognition",
        )

        report = DuplicateService.scan(title_similarity_threshold=0.8)

        assert report is not None
        assert report.state == DuplicateReportState.SUCCESS
        [match] = report.matches.filter(match_type=DuplicateMatchType.TITLE_SIMILARITY)
        assert match.score == 1.0

    def test_both_match_types(self, paper_a: Paper, paper_b: Paper) -> None:
        update_object(paper_b, title=paper_a.title)
        paper_a.submissions.create(revision=1, file="paper.pdf", sha256="aaa")
        paper_b.submissions.create(revision=1, file="paper.pdf", sha256="aaa")

        report = DuplicateService.scan(title_similarity_threshold=0.8)

        assert report is not None
        hash_count = report.matches.filter(
            match_type=DuplicateMatchType.FILE_HASH
        ).count()
        title_count = report.matches.filter(
            match_type=DuplicateMatchType.TITLE_SIMILARITY
        ).count()
        assert hash_count == 1
        assert title_count == 1

    def test_no_matches(self, paper_a: Paper, paper_b: Paper) -> None:  # noqa: ARG002
        report = DuplicateService.scan()

        assert report is not None
        assert report.state == DuplicateReportState.SUCCESS
        assert DuplicateMatch.objects.filter(report=report).count() == 0

    def test_exceeds_paper_count_cap(self, paper_a: Paper, paper_b: Paper) -> None:  # noqa: ARG002
        report = DuplicateService.scan(paper_count_cap=1)

        assert report is not None
        assert report.state == DuplicateReportState.FAILED
        assert "1" in report.error_message

    def test_skip_when_no_changes(self, paper_a: Paper) -> None:  # noqa: ARG002
        first = DuplicateService.scan()
        assert first is not None

        second = DuplicateService.scan()
        assert second is None

    def test_no_skip_after_paper_update(self, paper_a: Paper) -> None:
        first = DuplicateService.scan()
        assert first is not None

        update_object(paper_a, title="Updated Title")
        second = DuplicateService.scan()
        assert second is not None

    def test_no_skip_after_new_submission(self, paper_a: Paper) -> None:
        first = DuplicateService.scan()
        assert first is not None

        paper_a.submissions.create(revision=1, file="paper.pdf", sha256="new")
        second = DuplicateService.scan()
        assert second is not None

    def test_skip_when_no_active_papers(self, paper_a: Paper) -> None:
        first = DuplicateService.scan()
        assert first is not None

        update_object(paper_a, delete_time=timezone.now())
        second = DuplicateService.scan()
        assert second is None

    def test_retention_cleanup(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        for i in range(5):
            Paper.objects.create(
                conference=conference,
                track=track,
                code=f"RET-{i:03d}",
                owner=user,
                title=f"Retention Paper {i}",
            )
            DuplicateService.scan(retention_successful=2)

        assert (
            DuplicateReport.objects.filter(state=DuplicateReportState.SUCCESS).count()
            == 2
        )

    def test_retention_cleanup_failed(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        for i in range(4):
            Paper.objects.create(
                conference=conference,
                track=track,
                code=f"FRET-{i:03d}",
                owner=user,
                title=f"Failed Retention Paper {i}",
            )
            DuplicateService.scan(paper_count_cap=0, retention_failed=1)

        assert (
            DuplicateReport.objects.filter(state=DuplicateReportState.FAILED).count()
            == 1
        )

    def test_scan_window_excludes_old_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        old_paper = Paper.objects.create(
            conference=conference,
            track=track,
            code="OLD-001",
            owner=user,
            title="Old Paper",
            create_time=timezone.now() - timedelta(days=400),
        )
        recent_paper = Paper.objects.create(
            conference=conference,
            track=track,
            code="NEW-001",
            owner=user,
            title="Old Paper",
        )
        old_paper.submissions.create(revision=1, file="paper.pdf", sha256="aaa")
        recent_paper.submissions.create(revision=1, file="paper.pdf", sha256="aaa")

        report = DuplicateService.scan(scan_window=timedelta(days=365))

        assert report is not None
        assert report.state == DuplicateReportState.SUCCESS
        # Only one paper is within the window, so no pairs can be formed.
        assert DuplicateMatch.objects.filter(report=report).count() == 0

    def test_scan_window_includes_recent_papers(
        self,
        user: User,
        conference: Conference,
        track: Track,
    ) -> None:
        for i in range(2):
            p = Paper.objects.create(
                conference=conference,
                track=track,
                code=f"WIN-{i:03d}",
                owner=user,
                title="Identical Title",
            )
            p.submissions.create(revision=1, file="paper.pdf", sha256="same")

        report = DuplicateService.scan(scan_window=timedelta(days=365))

        assert report is not None
        assert DuplicateMatch.objects.filter(report=report).count() > 0

    def test_uses_latest_submission_hash(self, paper_a: Paper, paper_b: Paper) -> None:
        paper_a.submissions.create(revision=1, file="paper.pdf", sha256="old")
        paper_a.submissions.create(revision=2, file="paper.pdf", sha256="aaa")
        paper_b.submissions.create(revision=1, file="paper.pdf", sha256="aaa")

        report = DuplicateService.scan()

        assert report is not None
        assert (
            report.matches.filter(match_type=DuplicateMatchType.FILE_HASH).count() == 1
        )

    def test_uses_latest_final_hashes(self, paper_a: Paper, paper_b: Paper) -> None:
        paper_a.finals.create(
            revision=1,
            source_file="source.zip",
            source_sha256="old_src",
            viewable_sha256="old_view",
        )
        paper_a.finals.create(
            revision=2,
            source_file="source.zip",
            source_sha256="src",
            viewable_sha256="view",
        )
        paper_b.finals.create(
            revision=1,
            source_file="source.zip",
            source_sha256="src",
            viewable_sha256="view",
        )

        report = DuplicateService.scan()

        assert report is not None
        # source and viewable both match, but the pair is deduped.
        assert (
            report.matches.filter(match_type=DuplicateMatchType.FILE_HASH).count() == 1
        )
