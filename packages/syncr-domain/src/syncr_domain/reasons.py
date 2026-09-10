"""The reason record: why a block is where it is, as values rather than as prose.

Explainability is a product commitment, and a sentence that cannot be traced to a value the solver
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

**Three vocabularies, not two overloaded ones.** A task the search places outright is neither
a binding nor a derivation: its content was never drawn from anywhere and nothing determined
it but the search itself. It names :class:`PlacedSource`, so neither existing vocabulary has
to hold a member it cannot hold honestly.

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


class PlacedSource(StrEnum):
    """A placement the solver chose outright.

    Read by the ``bound`` clause for a task the search placed itself. A habit occurrence whose
    ``queue`` binding drew that same task keeps :class:`~syncr_domain.habits.BindingSource`'s
    member, which names where the occurrence's CONTENT came from; this arm names a placement
    nobody chose but the solver, so the two do not share a word on the wire.
    """

    SOLVER = "solver"


type BoundSource = BindingSource | DerivationSource | PlacedSource
"""What a ``bound`` clause names: a habit's binding source, a derivation, or a placement the
solver chose.

A union of the three vocabularies rather than one list of eight strings.
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
    """The objective term with the largest share of the PLAN's total cost.

    The plan's, not this block's. The objective measures a whole week and three of its seven terms
    have no per-block reading at all:

    - ``budget_deviation`` is an Area's gap against a whole-week target, divided by the total of
      those targets, so it is a fraction of something no single block is part of;
    - ``staleness`` counts the minutes of occurrences the plan places NOWHERE, so there is no block
      for it to attach to;
    - ``churn`` is a saturating curve over the number of moves against a tolerance, which is not
      decomposable per block even in principle: two blocks that each moved cost less together than
      twice what one costs alone.

    So the share is ``cost of the term / cost of the plan``, which is the figure the breakdown
    already answers, and every block of one plan carries the same one. A per-block share would need
    an attribution rule invented for each of the three, to satisfy a sentence rather than to answer
    a question the objective asks.
    """

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

    One clause kind serves both because the kinds are distinguished by the source rather than
    by more kinds: a habit's binding source names how the content was chosen, a derivation
    source names what fixed the block outright, and a placed source names a placement the
    solver chose.
    """

    source: BoundSource
    selected: str
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class Floor:
    """An Area's declared floor, the rule's remaining floor, and its reservation."""

    area_id: AreaId
    declared_floor_minutes: int
    floor_minutes: int
    placed: int
    of: int

    def __post_init__(self) -> None:
        negative = {
            name: value
            for name, value in (
                ("declared_floor_minutes", self.declared_floor_minutes),
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
#
# **The key order is the order the rows are rendered in**, so the same mapping states the
# vocabulary, the bound and the reading order rather than three lists to keep in step. The
# order runs from what is most specific about this block to what is most general about the
# week: what determined it, then the user's own edit and what that edit replaced, then the
# windows the rules refused, then the term carrying the plan's cost, then the Area floor.
CLAUSE_BUDGET: Final[Mapping[type[Clause], int]] = {
    Bound: 1,
    Pinned: 1,
    InsteadOf: 1,
    Blocked: 2,
    Dominant: 1,
    Floor: 1,
}

MAX_CLAUSES: Final = sum(CLAUSE_BUDGET.values())

# Each kind's position in the reading order, derived from the budget's own keys so a seventh
# kind cannot be renderable without being budgeted.
_RANK: Final[Mapping[type[Clause], int]] = {kind: rank for rank, kind in enumerate(CLAUSE_BUDGET)}


@dataclass(frozen=True, slots=True)
class ReasonRecord:
    """Why one block is where it is. At least one clause, and never more than the budget.

    The clauses are held as a tuple whatever the caller passed, so a record read back from a
    stored document cannot be changed through the list it was built from.

    **They are held in the reading order** :data:`CLAUSE_BUDGET` states, whatever order they
    arrived in, so one record has one rendering wherever it was built and whichever surface
    draws it. Two clauses of one kind keep the order the caller gave them, which is what makes
    the top two rejected windows readable as first and second.
    """

    clauses: tuple[Clause, ...]

    def __post_init__(self) -> None:
        clauses = tuple(self.clauses)
        if not clauses:
            raise ReasonError(
                "a block carries at least one clause: a block with no reason is one the "
                "interface can render but not explain, and a block fixed by derivation "
                "satisfies this with a single 'bound' clause naming its determinant"
            )
        _require_the_budget(clauses)
        object.__setattr__(self, "clauses", tuple(sorted(clauses, key=_rank_of)))


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


def _rank_of(clause: Clause) -> int:
    """Where this clause reads in the record. Safe only after the budget check named the kind."""
    return _RANK[type(clause)]


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
