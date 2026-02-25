"""Paper claim service for deferred ownership transfer.

When admins create papers on behalf of authors, the admin becomes the paper owner.
A "claim" records the intended author's email so that ownership transfers automatically
when that author registers an account.

Claim lifecycle:
    - **Created** by ``set_claim`` (or ``create_paper`` with ``auto_claim=True``). If a
      user with the derived email already exists, ownership transfers immediately and no
      claim is stored.
    - **Fulfilled** by ``fulfill_claims`` during user registration: ownership transfers
      to the new user, and the claim is deleted via ``transfer_paper``.
    - **Invalidated** by ``PaperService.update_paper`` when author changes make the
      claim email stale (different email or no longer determinable).
    - **Removed** explicitly by the ``remove-claim`` endpoint, by ``transfer_paper``
      (an explicit transfer supersedes any pending claim), or by ``delete_paper``
      (a deleted paper should not transfer on registration).

Concurrency:
    Operations that create or fulfill claims acquire an email-scoped mutex (namespace
    ``"paper_claim"``) to serialize the check-then-act between claim creation and user
    registration. Operations that mutate or delete claims also acquire the paper-scoped
    mutex (namespace ``"paper"``). When both locks are needed, email lock is always
    acquired first to prevent deadlocks.
"""

from django.utils.translation import gettext as _

from app.conference.models import Paper, PaperAuthor, PaperClaim
from app.conference.services.paper import PaperService
from app.core.models import User
from app.infra.models import Mutex


class ClaimConflictError(Exception):
    """The claim could not be set due to a concurrent modification."""


class ClaimService:
    @classmethod
    def derive_claim_email(cls, paper: Paper) -> str:
        """Derive the claim email from the paper's corresponding author.

        Exactly one author must be marked as corresponding and have a non-empty email
        address.

        Raises:
            ValueError: If zero or multiple corresponding authors exist, or the single
                corresponding author has no email.
        """
        authors = PaperAuthor.objects.filter(paper=paper, corresponding=True)
        matches = list(authors.values_list("email", flat=True)[:2])

        if len(matches) != 1:
            raise ValueError(_("Paper must have exactly one corresponding author."))

        [email] = matches
        if not email:
            raise ValueError(_("The corresponding author must have an email address."))

        return email.lower()

    @classmethod
    def set_claim(cls, paper: Paper) -> PaperClaim | None:
        """Create a claim on the paper for deferred ownership transfer.

        Derives the claim email from the corresponding author. If a user with that email
        already exists, transfers ownership immediately and returns ``None``. Otherwise,
        creates a ``PaperClaim`` for automatic transfer when the user registers. No-op
        if a claim with the same email already exists.

        Raises:
            ValueError: If the corresponding author cannot be determined.
            ClaimConflictError: If the paper's authors were modified concurrently,
                invalidating the email lock. The caller should retry.
            Paper.DoesNotExist: If the paper has been deleted or deactivated.
        """
        # Optimistic pre-read: derive email before acquiring locks.
        email = cls.derive_claim_email(paper)

        with (
            Mutex.lock_in_transaction(email, namespace="paper_claim"),
            Mutex.lock_in_transaction(str(paper.pk), namespace="paper"),
        ):
            paper = Paper.objects.active().get(pk=paper.pk)
            verified_email = cls.derive_claim_email(paper)
            if verified_email != email:
                raise ClaimConflictError(_("Paper authors were modified concurrently."))

            user = User.objects.active().filter(email__iexact=email).first()
            if user is not None:
                PaperService.transfer_paper(paper=paper, new_owner=user)
                return None

            claim, __ = PaperClaim.objects.update_or_create(
                paper=paper,
                defaults={"email": email},
            )
            return claim

    @classmethod
    def remove_claim(cls, paper: Paper) -> None:
        """Delete the claim on a paper, if one exists.

        Acquires the paper lock to serialize with concurrent dispatch handlers.
        """
        with Mutex.lock_in_transaction(str(paper.pk), namespace="paper"):
            PaperClaim.objects.filter(paper=paper).delete()

    @classmethod
    def fulfill_claims(cls, user: User) -> list[str]:
        """Fulfill all pending claims matching the user's email.

        Called during user registration. Transfers ownership of all claimed papers to
        the new user and deletes the fulfilled claims.
        """
        email = user.email.lower()

        with Mutex.lock_in_transaction(email, namespace="paper_claim"):
            claims = list(PaperClaim.objects.filter(email__iexact=email))

            transferred: list[str] = []
            for claim in claims:
                with Mutex.lock_in_transaction(str(claim.paper_id), namespace="paper"):
                    # Re-verify the claim still exists; it may have been removed by a
                    # concurrent `remove_claim` or `update_paper`.
                    if not PaperClaim.objects.filter(
                        pk=claim.pk
                    ).exists():  # pragma: no cover
                        continue

                    try:
                        # Paper lock is already held; transfer_paper re-acquires it
                        # (re-entrant) and handles claim deletion internally.
                        paper = PaperService.transfer_paper(
                            paper=Paper(pk=claim.paper_id),
                            new_owner=user,
                        )
                    except Paper.DoesNotExist:
                        continue

                    transferred.append(paper.code)

            return transferred
