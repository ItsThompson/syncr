"""The reason record: why a block is where it is, as values rather than as prose.

Explainability is a P0 feature, and a sentence that cannot be traced to a value the solver
computed is worse than no sentence. So the reason is a structured record and the interface
renders it through one template per clause kind. No language model sits in the placement
loop, and the panel draws labeled rows rather than a paragraph, because a paragraph implies
unbounded prose and this shape is bounded.

**Six clause kinds, and the widening that keeps it at six.** ``materialize`` runs no search,
evaluates no objective, and reads no weight set, so five of the six kinds have nothing to
draw on for a block whose placement was determined rather than chosen. Rather than carve an
exception into the rule that every block carries a reason, ``bound`` accepts a derivation
source alongside the three habit binding sources. A derived block therefore satisfies the
one-clause minimum with a single ``bound`` clause naming its determinant, and the detail
panel has real content for the frame, anchor, prep, and transit blocks that are about 45% of
a solved week.

**The budget is a bound on storage, not a style.** A revision document lives in an
append-only store forever, so recording every rejected candidate for every block would bloat
it without end. Two rejected windows are the most any block reports, and one of each other
kind.

**No clause names a rule vocabulary this package owns.** The hard-constraint rules are the
solver's, and the solver depends on this package rather than the other way round, so
``Blocked.rule`` is typed as text. A ``StrEnum`` member from the solver satisfies it, which
is how the closed vocabulary reaches the clause without inverting the dependency.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.habits import BindingSource

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AreaId, PlanRevisionId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.zones import Date

# The largest share of total cost one objective term can hold. A share is a fraction of the
# whole, so a term claiming more than the whole is an arithmetic fault upstream.
MAX_SHARE: Final = 1.0


class ReasonError(DomainError):
    """A reason record breaks the clause budget, or states no reason at all."""


class DerivationSource(StrEnum):
    """What determined a block whose placement nobody chose.

    Read by the ``bound`` clause for the four kinds of block the solver never places: the
    frame, a concrete template entry, an imported anchor, and a buffer an anchor's type cast.
    """

    ROUTINE = "routine"
    TEMPLATE_ENTRY = "template_entry"
    ANCHOR = "anchor"
    ANCHOR_TYPE = "anchor_type"


type BoundSource = BindingSource | DerivationSource
"""What a ``bound`` clause names: a habit's binding source, or a derivation.

A union of the two vocabularies rather than a third list of seven strings.
:class:`~syncr_domain.habits.BindingSource` already states ``fixed``, ``rotation``, and
``queue``, and restating them here would leave two definitions of one set to drift.
"""


@dataclass(frozen=True, slots=True)
class ChurnBaseline:
    """Which plan churn was measured against, or the statement that there is none.

    Churn is measured against the last APPROVED revision, because "the last plan the user
    saw" is not a persistable definition and "the week I signed off" already is. A week that
    has never been approved has zero churn, and the clause says so rather than silently
    comparing against a proposal nobody agreed to.

    The two fields are set together or not at all, so the record cannot claim a baseline it
    cannot name. Which of the two cases this is, is read from :attr:`is_measured` rather than
    stored beside them: a third field could disagree with the pair.

    **The solver has a same-named type whose ``is_measured`` answers differently.**
    ``syncr_solver.inputs.ChurnBaseline`` is the objective's input and it carries the approved
    PLAN as well, so its ``is_measured`` asks whether there is a document to compare against;
    this one is the render-time value and asks whether a revision was named. The two disagree
    wherever a revision is named but its document is not readable. Both are right for their own
    question, and a caller converting between them states which it is asking.
    """

    revision_id: PlanRevisionId | None = None
    approved_at: Instant | None = None

    def __post_init__(self) -> None:
        if (self.revision_id is None) != (self.approved_at is None):
            raise ReasonError(
                "a churn baseline names an approved revision and the instant of assent, or "
                "neither: the clause renders the date, so half a baseline renders half a "
                "sentence"
            )

    @property
    def is_measured(self) -> bool:
        """Whether a plan was approved for churn to be measured against."""
        return self.revision_id is not None


@dataclass(frozen=True, slots=True)
class Blocked:
    """A candidate window, and the hard constraint that rejected it.

    ``rule`` is the constraint checker's own vocabulary, which lives in the solver. It is
    typed as text here because this package must not import the solver, and a ``StrEnum``
    member there is text.
    """

    window: Interval
    rule: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Dominant:
    """The objective term with the largest share of this block's cost."""

    term: str
    share: float
    baseline: ChurnBaseline | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.share <= MAX_SHARE:
            raise ReasonError(
                f"a term's share of total cost runs from 0 to {MAX_SHARE}, and this one is "
                f"{self.share}: a share above the whole is an arithmetic fault in the "
                "breakdown rather than a dominant term"
            )


@dataclass(frozen=True, slots=True)
class Bound:
    """What determined this block's content, or its whole placement.

    One clause kind serves both because the two are distinguished by the source rather than
    by a second kind: a habit's binding source names how the content was chosen, and a
    derivation source names what fixed the block outright.
    """

    source: BoundSource
    selected: str
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class Floor:
    """An Area floor that forced or forbade this placement."""

    area_id: AreaId
    floor_minutes: int
    placed: int
    of: int

    def __post_init__(self) -> None:
        negative = {
            name: value
            for name, value in (
                ("floor_minutes", self.floor_minutes),
                ("placed", self.placed),
                ("of", self.of),
            )
            if value < 0
        }
        if negative:
            stated = ", ".join(f"{name}={value}" for name, value in sorted(negative.items()))
            raise ReasonError(
                f"a floor clause counts minutes, so none of these is negative: {stated}"
            )


@dataclass(frozen=True, slots=True)
class Pinned:
    """The user's own edit, and the date they made it."""

    at: Interval
    pinned_on: Date


@dataclass(frozen=True, slots=True)
class InsteadOf:
    """The placement a pin overrode, and what overriding it cost.

    The delta is stored rather than recomputed later, because the weight set that produced it
    is versioned and will have moved on.
    """

    placement: Interval
    objective_delta: float

    def __post_init__(self) -> None:
        require_a_finite_delta(self.objective_delta)


type Clause = Blocked | Dominant | Bound | Floor | Pinned | InsteadOf
"""The six kinds, and nothing else. Widening this needs an entry in the budget below."""


# One statement per kind, keyed on the kinds themselves rather than on a parallel list of
# names: a seventh clause reaches the budget or is refused at construction. Two rejected
# windows is the most any block reports, because the panel shows the top two.
CLAUSE_BUDGET: Final[Mapping[type[Clause], int]] = {
    Blocked: 2,
    Dominant: 1,
    Bound: 1,
    Floor: 1,
    Pinned: 1,
    InsteadOf: 1,
}

MAX_CLAUSES: Final = sum(CLAUSE_BUDGET.values())


@dataclass(frozen=True, slots=True)
class ReasonRecord:
    """Why one block is where it is. At least one clause, and never more than the budget.

    The clauses are held as a tuple whatever the caller passed, so a record read back from a
    stored document cannot be changed through the list it was built from.
    """

    clauses: tuple[Clause, ...]

    def __post_init__(self) -> None:
        clauses = tuple(self.clauses)
        object.__setattr__(self, "clauses", clauses)
        if not clauses:
            raise ReasonError(
                "a block carries at least one clause: a block with no reason is one the "
                "interface can render but not explain, and a block fixed by derivation "
                "satisfies this with a single 'bound' clause naming its determinant"
            )
        _require_the_budget(clauses)


def require_a_finite_delta(objective_delta: float) -> None:
    """Raise unless ``objective_delta`` is a real number of objective units.

    A NaN would compare false against every threshold and render as ``nan``, and an infinity
    would make any sum of deltas infinite. Both are arithmetic faults upstream rather than
    costs a pin can have, and both are storable in JSON only as something else.
    """
    if not math.isfinite(objective_delta):
        raise ReasonError(
            f"an objective delta is a finite number of objective units, and {objective_delta} "
            "is not one: it would render as itself and compare false against every threshold"
        )


def _require_the_budget(clauses: Sequence[Clause]) -> None:
    counted = Counter(type(clause) for clause in clauses)
    unknown = sorted(kind.__name__ for kind in counted if kind not in CLAUSE_BUDGET)
    if unknown:
        raise ReasonError(
            f"a reason record holds the six clause kinds and not {', '.join(unknown)}: the "
            "interface renders one template per kind, so a kind with no template renders "
            "nothing at all"
        )
    over = sorted(
        (kind.__name__, count, CLAUSE_BUDGET[kind])
        for kind, count in counted.items()
        if count > CLAUSE_BUDGET[kind]
    )
    if over:
        stated = ", ".join(f"{name} {count} of {allowed}" for name, count, allowed in over)
        raise ReasonError(
            f"a reason record is bounded per clause kind and this one exceeds it: {stated}. "
            "A revision document is appended forever, so an unbounded record grows one"
        )
