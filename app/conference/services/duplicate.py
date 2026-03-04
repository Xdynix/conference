from datetime import datetime, timedelta
from itertools import combinations
from typing import NamedTuple, TypedDict, cast

from django.db.models import Max, OuterRef, QuerySet, Subquery
from django.utils import timezone
from rapidfuzz import fuzz

from app.conference.models import DuplicateMatch, DuplicateReport
from app.conference.models.duplicate import DuplicateMatchType, DuplicateReportState
from app.conference.models.paper import Paper, PaperFinal, PaperSubmission
from app.infra.models import Mutex

MUTEX_NAMESPACE = "duplicate_scan"
MUTEX_KEY = "global"


class DuplicatePaperRow(TypedDict):
    pk: int
    title: str
    submission_sha256: str | None
    final_source_sha256: str | None
    final_viewable_sha256: str | None


class MatchPair(NamedTuple):
    paper_a_id: int
    paper_b_id: int
    score: float


def match_file_hash(papers: list[DuplicatePaperRow]) -> list[MatchPair]:
    """Find pairs of papers that share at least one file hash."""
    hash_fields = (
        "submission_sha256",
        "final_source_sha256",
        "final_viewable_sha256",
    )
    hash_to_pks: dict[str, set[int]] = {}
    for paper in papers:
        for key in hash_fields:
            h = paper[key]  # type: ignore[literal-required]
            if h:
                hash_to_pks.setdefault(h, set()).add(paper["pk"])

    seen: set[tuple[int, int]] = set()
    matches: list[MatchPair] = []
    for pks in hash_to_pks.values():
        if len(pks) < 2:
            continue
        for a, b in combinations(sorted(pks), 2):
            if (a, b) not in seen:
                seen.add((a, b))
                matches.append(MatchPair(paper_a_id=a, paper_b_id=b, score=1.0))
    return matches


def match_title_similarity(
    papers: list[DuplicatePaperRow],
    threshold: float,
) -> list[MatchPair]:
    """Find pairs of papers whose titles exceed the similarity threshold."""
    matches: list[MatchPair] = []
    for a, b in combinations(papers, 2):
        score = fuzz.token_set_ratio(a["title"], b["title"]) / 100.0
        if score >= threshold:
            pk_a, pk_b = sorted((a["pk"], b["pk"]))
            matches.append(MatchPair(paper_a_id=pk_a, paper_b_id=pk_b, score=score))
    return matches


class DuplicateService:
    @classmethod
    def scan(
        cls,
        *,
        scan_window: timedelta = timedelta(days=365 * 3),
        paper_count_cap: int = 5000,
        title_similarity_threshold: float = 0.85,
        retention_successful: int = 3,
        retention_failed: int = 2,
    ) -> DuplicateReport | None:
        """Run a full duplicate detection scan.

        Args:
            scan_window: How far back from now to include papers (by ``create_time``).
            paper_count_cap: Maximum number of papers in the scan window before the scan
                aborts with a failed report.
            title_similarity_threshold: Minimum token-set ratio (0.0 to 1.0) for a title
                pair to be recorded as a match.
            retention_successful: Number of successful reports to keep after cleanup.
            retention_failed: Number of failed reports to keep after cleanup.

        Returns the new report, or ``None`` if the scan was skipped because nothing has
        changed since the last successful run.
        """
        with Mutex.lock_in_transaction(MUTEX_KEY, namespace=MUTEX_NAMESPACE):
            if cls._should_skip():
                return None

            qs = cls._paper_queryset(timezone.now() - scan_window)
            papers: list[DuplicatePaperRow] = list(qs[: paper_count_cap + 1])
            if len(papers) > paper_count_cap:
                report = DuplicateReport.objects.create(
                    state=DuplicateReportState.FAILED,
                    error_message=f"More than {paper_count_cap} papers in scan window.",
                )
                cls._enforce_retention(retention_successful, retention_failed)
                return report

            hash_matches = match_file_hash(papers)
            title_matches = match_title_similarity(
                papers,
                title_similarity_threshold,
            )

            report = DuplicateReport.objects.create()
            DuplicateMatch.objects.bulk_create(
                [
                    DuplicateMatch(
                        report=report,
                        paper_a_id=m.paper_a_id,
                        paper_b_id=m.paper_b_id,
                        match_type=match_type,
                        score=m.score,
                    )
                    for match_type, matches in (
                        (DuplicateMatchType.FILE_HASH, hash_matches),
                        (DuplicateMatchType.TITLE_SIMILARITY, title_matches),
                    )
                    for m in matches
                ]
            )
            cls._enforce_retention(retention_successful, retention_failed)
            return report

    @classmethod
    def _should_skip(cls) -> bool:
        """Check whether anything changed since the last successful report.

        Compares the latest successful report's timestamp against the most recent
        ``Paper.update_time`` and ``PaperSubmission.create_time``. Returns ``True``
        if no data has changed.
        """
        last_report: datetime | None = (
            DuplicateReport.objects.filter(state=DuplicateReportState.SUCCESS)
            .order_by("-create_time")
            .values_list("create_time", flat=True)
            .first()
        )
        if last_report is None:
            return False

        changes = Paper.objects.active().aggregate(
            latest_paper_change=Max("update_time"),
            latest_submission=Max("submission__create_time"),
        )
        last_change: datetime | None = max(
            filter(
                None,
                [changes["latest_paper_change"], changes["latest_submission"]],
            ),
            default=None,
        )
        if last_change is None:
            return True

        return last_change <= last_report

    @classmethod
    def _paper_queryset(cls, cutoff: datetime) -> QuerySet[DuplicatePaperRow]:  # type: ignore[type-var]
        """Build queryset for scan rows with the latest hashes per paper.

        Each row contains ``pk``, ``title``, and latest submission/final SHA-256 values;
        it does not materialize related model instances.
        """
        latest_submission_sha256 = (
            PaperSubmission.objects.filter(paper_id=OuterRef("pk"))
            .order_by("-revision")
            .values("sha256")[:1]
        )
        latest_finals = PaperFinal.objects.filter(paper_id=OuterRef("pk")).order_by(
            "-revision"
        )
        qs = (
            Paper.objects.active()
            .filter(create_time__gte=cutoff)
            .annotate(
                submission_sha256=Subquery(latest_submission_sha256),
                final_source_sha256=Subquery(latest_finals.values("source_sha256")[:1]),
                final_viewable_sha256=Subquery(
                    latest_finals.values("viewable_sha256")[:1]
                ),
            )
            .values(
                "pk",
                "title",
                "submission_sha256",
                "final_source_sha256",
                "final_viewable_sha256",
            )
        )
        return cast(QuerySet[DuplicatePaperRow], qs)  # type: ignore[type-var]

    @classmethod
    def _enforce_retention(
        cls,
        retention_successful: int,
        retention_failed: int,
    ) -> None:
        """Delete old reports beyond the retention limits, per status category."""
        for state, keep in (
            (DuplicateReportState.SUCCESS, retention_successful),
            (DuplicateReportState.FAILED, retention_failed),
        ):
            stale_ids = list(
                DuplicateReport.objects.filter(state=state)
                .order_by("-create_time", "-pk")
                .values_list("pk", flat=True)[keep:]
            )
            DuplicateReport.objects.filter(pk__in=stale_ids).delete()
