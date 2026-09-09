"""The plan churn baseline and the pairing its rendered reason requires."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.intervals import as_instant
from syncr_domain.plan import PlanError

if TYPE_CHECKING:
    from syncr_domain.identifiers import PlanRevisionId
    from syncr_domain.intervals import Instant
    from syncr_domain.plan import PlanDocument


@dataclass(frozen=True, slots=True, kw_only=True)
class ChurnBaseline:
    """The plan churn is measured against, or a statement of why there is none.

    "The last plan the user saw" is not a persistable definition, so churn is measured
    against the last plan the user APPROVED. A week that has never been approved has zero
    churn and says so, rather than silently comparing against a proposal nobody approved.

    ``document`` is the plan those minutes are compared with, and it is here rather than on
    ``SolveInputs`` beside ``live_plan`` because the two are DIFFERENT documents:
    ``live_plan`` is the newest revision whatever its status, and an ``applied`` revision can
    be newer than the newest ``approved`` one. Measured against ``live_plan``, churn would be
    measured against a plan the user never signed off, which is the definition this baseline
    exists to refuse.

    ## Three states on two fields, and ``reason`` is derived from them

    A baseline names no revision, or names one and carries its plan, or names one whose plan
    this deployment cannot read. The third is not a defect: reading a stored document back
    through the domain constructors can fail on a document this deployment cannot rebuild, and
    churn goes uncharged rather than measured against a plan nobody supplied.

    ``reason`` is a property rather than a field, so it cannot disagree with the fields it
    describes. A renderer reads it and gets a distinct answer per state; a renderer reading only
    ``revision_id`` would render "measured against the plan you approved on Sun 09 Feb" for a
    churn of zero, claiming a comparison that never happened.

    ## The name collides with a domain type, and so does ``is_measured``

    :class:`syncr_domain.reasons.ChurnBaseline` is the value a ``dominant`` clause renders from,
    and its own ``is_measured`` reads ``revision_id is not None``. **The two answer differently**
    wherever a revision is named whose plan is not in hand: that one says a baseline exists
    because a revision is named, and this one says churn can be measured only when the plan to
    measure against is in hand. Both are right for their own question. A caller converting between
    them states which it is asking.

    **The pairing invariant is the domain twin's, for the reason a clause renders from it.** A
    plan with no revision named would make ``is_measured`` true while ``reason`` said
    ``never-approved``, and a ``dominant`` clause built from it would cite churn while naming no
    revision and no date, which a clause may never render. Unreachable through the two
    constructors and refused by the type anyway, because the clause's own guarantee is stated as a
    property of this value rather than of one producer.
    """

    revision_id: PlanRevisionId | None = None
    approved_at: Instant | None = None
    document: PlanDocument | None = None

    NEVER_APPROVED = "never-approved"
    APPROVED_REVISION = "approved-revision"
    APPROVED_UNREADABLE = "approved-revision-unreadable"

    def __post_init__(self) -> None:
        _require_a_named_revision_for_a_readable_plan(
            self.revision_id, self.approved_at, self.document
        )

    @classmethod
    def never_approved(cls) -> ChurnBaseline:
        """The baseline of a week no revision of which the user has assented to."""
        return cls()

    @classmethod
    def approved(
        cls,
        revision_id: PlanRevisionId,
        approved_at: Instant,
        document: PlanDocument | None = None,
    ) -> ChurnBaseline:
        """The baseline naming the revision the user approved, when, and its plan where readable."""
        return cls(
            revision_id=revision_id,
            approved_at=as_instant(approved_at),
            document=document,
        )

    @property
    def reason(self) -> str:
        """Which of the three states this baseline is in, as the word a clause renders."""
        if self.revision_id is None:
            return self.NEVER_APPROVED
        return self.APPROVED_REVISION if self.document is not None else self.APPROVED_UNREADABLE

    @property
    def is_measured(self) -> bool:
        """Whether there is a plan for churn to be the difference from.

        The document rather than the revision id, because a revision this deployment can name but
        not read gives the term nothing to compare against. This is the property that differs from
        the same-named one on ``syncr_domain.reasons.ChurnBaseline``; see the class docstring.
        """
        return self.document is not None


def _require_a_named_revision_for_a_readable_plan(
    revision_id: PlanRevisionId | None, approved_at: Instant | None, document: PlanDocument | None
) -> None:
    """A baseline names the revision and the instant of assent together, or names neither.

    Two refusals, and the second is what the ``dominant`` clause depends on. Half a baseline
    renders half a sentence, which is the domain twin's own rule. And a plan carried without a
    revision to name it would make :attr:`ChurnBaseline.is_measured` true while ``reason`` still
    read ``never-approved``, so churn could be charged against a document the clause cannot cite:
    the clause would say the plan moved and name nothing it moved from.
    """
    if (revision_id is None) != (approved_at is None):
        raise PlanError(
            "a churn baseline names an approved revision and the instant of assent, or neither: "
            "the clause renders the date, so half a baseline renders half a sentence"
        )
    if document is not None and revision_id is None:
        raise PlanError(
            "a churn baseline carrying a plan names the revision that plan is: churn measured "
            "against a document no revision names is a cost the reason record cannot cite, and "
            "the clause has to name the revision and its date"
        )
