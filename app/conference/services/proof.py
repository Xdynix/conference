from collections.abc import Mapping, Sequence
from typing import ClassVar

from django.core.exceptions import ObjectDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from app.conference.models import Paper, PaperAuthor, PaperProof, PaperState
from app.utils.files import validate_upload


class ProofEligibilityError(Exception):
    """Raised when a paper is not eligible for proof creation."""


class RecipientDerivationError(Exception):
    """Raised when recipient name or email cannot be derived.

    Attributes:
        missing_fields: List of field names that could not be derived.
    """

    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(f"Cannot derive: {', '.join(missing_fields)}")


# No Mutex is used for proof operations. Unlike revision uploads (which require
# read-then-write sequencing for revision numbers), proof is a singleton resource with
# admin-only mutations. Concurrent access is unlikely and the worst case is an orphaned
# file in storage. Add a Mutex if this assumption changes.


class ProofService:
    _ELIGIBLE_STATES: ClassVar[set[str]] = {
        PaperState.ACCEPTED,
        PaperState.ACCEPTED_REVISION_NEEDED,
    }

    @classmethod
    def _check_eligibility(cls, paper: Paper) -> None:
        """Verify that a paper is eligible for proof creation.

        Requires an accepted (or accepted-revision-needed) paper that has been
        announced, not withdrawn, and not deleted.
        """
        if paper.delete_time is not None:
            raise ProofEligibilityError("Paper has been deleted.")
        if paper.state not in cls._ELIGIBLE_STATES:
            raise ProofEligibilityError("Paper is not in an accepted state.")
        if paper.announce_time is None:
            raise ProofEligibilityError("Decision has not been announced.")
        if paper.withdraw_time is not None:
            raise ProofEligibilityError("Paper has been withdrawn.")

    @classmethod
    def _derive_recipient(
        cls,
        paper: Paper,
        *,
        explicit_name: str = "",
        explicit_email: str = "",
    ) -> tuple[str, str]:
        """Derive recipient name and email, merging explicit overrides.

        Tries the first corresponding author (by ordering), then falls back to
        the paper owner's profile. Explicit values take precedence.

        Returns:
            Tuple of (recipient_name, recipient_email).

        Raises:
            RecipientDerivationError: If name or email is still empty after derivation
                and merging.
        """
        derived_name = ""

        corresponding = (
            PaperAuthor.objects.filter(paper=paper, corresponding=True)
            .order_by("ordering")
            .first()
        )
        if corresponding:
            given = corresponding.given_name
            family = corresponding.family_name
            derived_name = f"{given} {family}".strip()
            derived_email = corresponding.email
        else:
            try:
                profile = paper.owner.profile
                derived_name = f"{profile.given_name} {profile.family_name}".strip()
                derived_email = paper.owner.email
            except ObjectDoesNotExist:
                derived_email = paper.owner.email

        name = explicit_name or derived_name
        email = explicit_email or derived_email

        missing = []
        if not name:
            missing.append("recipient_name")
        if not email:
            missing.append("recipient_email")
        if missing:
            raise RecipientDerivationError(missing)

        return name, email

    @classmethod
    @transaction.atomic
    def upsert(
        cls,
        paper: Paper,
        *,
        recipient_name: str = "",
        recipient_email: str = "",
    ) -> PaperProof:
        """Create or update a proof record for a paper.

        Auto-derives recipient fields when not explicitly provided. Explicit values
        override derived ones.

        Raises:
            ProofEligibilityError: If the paper is not eligible.
            RecipientDerivationError: If recipient fields cannot be resolved.
        """
        cls._check_eligibility(paper)

        name, email = cls._derive_recipient(
            paper,
            explicit_name=recipient_name,
            explicit_email=recipient_email,
        )

        proof, created = PaperProof.objects.update_or_create(
            paper=paper,
            defaults={"recipient_name": name, "recipient_email": email},
        )
        if not created:
            # update_or_create doesn't cache FKs on the update path.
            proof.paper = paper
        return proof

    @classmethod
    def upload(
        cls,
        proof: PaperProof,
        file: UploadedFile,
        *,
        max_size: int = 0,
        allowed_types: Mapping[str, Sequence[str]] | None = None,
    ) -> PaperProof:
        """Upload a proof file, resetting confirmation if replacing an existing file.

        Validates the file before mutation. If the proof already has a file, clears
        confirmed_time, comment, and comment_time.

        Raises:
            app.utils.files.UploadValidationError: If file validation fails.
        """
        validate_upload(file, max_size=max_size, allowed_types=allowed_types)

        had_file = bool(proof.file)

        new_file_name: str | None = None
        try:
            proof.file.save(file.name, file, save=False)  # type: ignore[arg-type]
            new_file_name = proof.file.name

            update_fields = ["file", "update_time"]
            if had_file:
                proof.confirmed_time = None
                proof.comment = ""
                proof.comment_time = None
                update_fields += ["confirmed_time", "comment", "comment_time"]

            proof.save(update_fields=update_fields)
            return proof

        except Exception:
            if new_file_name:  # pragma: no branch
                proof.file.storage.delete(new_file_name)
            raise

    @classmethod
    def confirm(cls, proof: PaperProof) -> PaperProof:
        """Confirm a proof. Idempotent; confirming again is a no-op."""
        if proof.confirmed_time is not None:
            return proof
        proof.confirmed_time = timezone.now()
        proof.save(update_fields=["confirmed_time", "update_time"])
        return proof

    @classmethod
    def comment(cls, proof: PaperProof, text: str) -> PaperProof:
        """Upsert a comment on a proof."""
        proof.comment = text
        proof.comment_time = timezone.now()
        proof.save(update_fields=["comment", "comment_time", "update_time"])
        return proof
