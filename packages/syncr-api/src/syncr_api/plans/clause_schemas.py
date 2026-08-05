"""The six reason clauses on the wire, one shape each, and the record that holds them.

A clause is a Python type in the domain and a JSON object here, so the two need a discriminator
the domain does not carry: ``kind``. The words are the stored form's own, and a test crosses the
six declared here against the domain's clause budget, which is the table of what a record may
hold: a seventh kind reaching the domain has no shape here until it is given one.

The union is discriminated rather than a bare ``anyOf`` so the generated TypeScript narrows on one
field. The panel renders one template per kind, which is what makes the union closed: a client
that received a kind it has no template for would render nothing at all.

Beside ``document_schemas.py`` rather than inside it, mirroring the storage split one layer down:
the clause bodies are six independent pairs a reader can check one at a time, and the document
that carries them is its own concern.

**Every field is required except each shape's own ``kind``**, which carries the union's
discriminator and is set by the class rather than by a caller. The generator emits a discriminated
union's discriminator as required whatever its default, so the narrowing a client does is
unaffected.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Annotated, Literal, Self, assert_never
from uuid import UUID  # noqa: TC003 - as above

from pydantic import Field

from syncr_api.core.schemas import WireModel, WireSpan

# Every name here is used at runtime: the six clause types are matched on, ``ChurnBaseline`` is
# constructed, and ``BoundSource`` annotates a field, which pydantic resolves while the app is being
# built.
from syncr_domain.reasons import (
    Blocked,
    Bound,
    BoundSource,
    ChurnBaseline,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
)

if TYPE_CHECKING:
    from syncr_domain.reasons import Clause, ReasonRecord

_SHARE_DESCRIPTION = "This term's share of this block's total cost, from 0 to 1."
_RULE_DESCRIPTION = "The hard constraint that refused the window, in the checker's vocabulary."


class ChurnBaselineResponse(WireModel):
    """Which approved plan churn was measured against. Both halves are set, or neither.

    Neither means the week has never been approved, so churn is zero and the clause says why
    rather than silently comparing against a proposal nobody agreed to.
    """

    revision_id: UUID | None = Field(
        description="The approved revision churn is the difference from."
    )
    approved_at: datetime | None = Field(
        description="When it was approved, which the clause renders as a date."
    )

    @classmethod
    def of(cls, baseline: ChurnBaseline) -> Self:
        return cls(revision_id=baseline.revision_id, approved_at=baseline.approved_at)


class BlockedClause(WireModel):
    """A candidate window, and the hard constraint that rejected it."""

    kind: Literal["blocked"] = "blocked"
    window: WireSpan
    rule: str = Field(description=_RULE_DESCRIPTION)
    detail: str | None


class DominantClause(WireModel):
    """The objective term with the largest share of this block's cost."""

    kind: Literal["dominant"] = "dominant"
    term: str
    share: float = Field(description=_SHARE_DESCRIPTION)
    baseline: ChurnBaselineResponse | None = Field(
        description="Set when the term is churn: what it was measured against."
    )


class BoundClause(WireModel):
    """What determined this block's content, or its whole placement."""

    kind: Literal["bound"] = "bound"
    source: BoundSource = Field(
        description="How a habit's content was chosen, or what fixed a derived block outright."
    )
    selected: str
    cursor: str | None


class FloorClause(WireModel):
    """An Area floor that forced or forbade this placement."""

    kind: Literal["floor"] = "floor"
    area_id: UUID
    floor_minutes: int
    placed: int
    of: int


class PinnedClause(WireModel):
    """The user's own edit, and the date they made it."""

    kind: Literal["pinned"] = "pinned"
    at: WireSpan
    pinned_on: date


class InsteadOfClause(WireModel):
    """The placement a pin overrode, and what overriding it cost."""

    kind: Literal["instead_of"] = "instead_of"
    placement: WireSpan
    objective_delta: float


type ClauseResponse = Annotated[
    BlockedClause | DominantClause | BoundClause | FloorClause | PinnedClause | InsteadOfClause,
    Field(discriminator="kind"),
]
"""The six kinds and no seventh, discriminated so a client narrows on one field."""


class ReasonResponse(WireModel):
    """Why one block is where it is. At least one clause, never more than the budget."""

    clauses: list[ClauseResponse]

    @classmethod
    def of(cls, reason: ReasonRecord) -> Self:
        """The wire shape of one record. The budget is the domain's and holds already."""
        return cls(clauses=[as_clause(clause) for clause in reason.clauses])


def as_clause(clause: Clause) -> ClauseResponse:
    """One clause's wire shape. Total over the six, which ``assert_never`` is what holds.

    Dispatched on the type, as the stored form's writer is, rather than on a discriminator the
    domain does not carry: a seventh kind reaching the domain fails the type check here.
    """
    match clause:
        case Blocked():
            return BlockedClause(
                window=WireSpan.of(clause.window), rule=clause.rule, detail=clause.detail
            )
        case Dominant():
            return DominantClause(
                term=clause.term,
                share=clause.share,
                baseline=(
                    None if clause.baseline is None else ChurnBaselineResponse.of(clause.baseline)
                ),
            )
        case Bound():
            return BoundClause(source=clause.source, selected=clause.selected, cursor=clause.cursor)
        case Floor():
            return FloorClause(
                area_id=clause.area_id,
                floor_minutes=clause.floor_minutes,
                placed=clause.placed,
                of=clause.of,
            )
        case Pinned():
            return PinnedClause(at=WireSpan.of(clause.at), pinned_on=clause.pinned_on)
        case InsteadOf():
            return InsteadOfClause(
                placement=WireSpan.of(clause.placement), objective_delta=clause.objective_delta
            )
        case _:  # pragma: no cover - unreachable while the union holds six members
            assert_never(clause)
