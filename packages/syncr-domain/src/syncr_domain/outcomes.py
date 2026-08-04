"""What the outcome log says about one habit occurrence, and which states are a completion.

The rotation cursor and outstanding debt are both projections of the append-only outcome log.
Neither needs a whole ``BlockOutcome``: they need to know which occurrence of which habit a
row is about, what the user said happened, and whether the day was confirmed. That is what
:class:`HabitOutcome` holds, so the two derivations stay testable with literals and the plan
document's interior stays out of the pure package.

**The projection keys on the outcome's denormalized ``binding``**, which is why an outcome
survives its block's binding ceasing to exist and why correcting a past confirmation
re-derives the cursor and the debt with no further action: the derivations read the log from
scratch every time and there is no stored value for a correction to disagree with.

Exactly one of the five states is a miss. The other four each mean the content was done:

| State | Means | Reads as |
|---|---|---|
| ``presumed`` | nobody said otherwise, and the day was confirmed | a completion |
| ``completed`` | done as planned | a completion |
| ``partial`` | done, but not for as long as planned | a completion |
| ``moved`` | done, at a different time than planned | a completion |
| ``skipped`` | not done | a **miss** |

``presumed`` reads as a completion only once ``confirmed_at`` is set, which is the whole
point of the state: a block is presumed complete unless the user says otherwise, and
confirming the day is the user saying nothing otherwise. An unconfirmed row is neither: the
user disengaged from the day, so it is excluded from reviews and from learning, and it is
excluded here for the same reason. Confirming it later settles it in whichever direction the
user chooses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.identity import index_occurrence_key
from syncr_domain.intervals import as_instant

if TYPE_CHECKING:
    from syncr_domain.identifiers import HabitId
    from syncr_domain.intervals import Instant


class OutcomeState(StrEnum):
    """The five reality states one block's outcome can hold."""

    PRESUMED = "presumed"
    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    MOVED = "moved"


# The one state that says the content was not done. Named as its own constant because both
# derivations are stated against it, and because the completion set below is its complement
# rather than a second list that could drift from it.
MISS_STATE: Final = OutcomeState.SKIPPED

# Every state that says the content was done. Derived from the miss, so a state added to the
# vocabulary joins this set rather than falling silently outside both.
COMPLETION_STATES: Final = frozenset(OutcomeState) - {MISS_STATE}


@dataclass(frozen=True, slots=True)
class HabitOutcome:
    """One recorded outcome of one habit occurrence.

    ``occurrence_key`` is the occurrence's index within its week, assigned by the week assembler in
    expansion order and carried on the outcome's binding. Neither derivation reads it: it is here
    because it identifies WHICH occurrence a correction corrected, and because it is what the
    at-most-one-row-per-occurrence precondition on ``HabitOutcomeReader.read`` is stated over. A
    projection that dropped it could not be built from a binding either.

    The key is checked against the one derivation of it rather than described a second time, so a
    row spelling an index some other way is refused here instead of silently matching no block.
    Nothing compares an outcome to a block yet, which is exactly why the two spellings have to be
    held together now: the first comparison would otherwise never fire and report nothing.

    Both instants are normalized on construction, so a naive datetime is refused rather than
    compared against a wall clock later. Two of those comparing without error is how a
    transition-week defect becomes invisible, which is the reason ``as_instant`` exists.
    """

    habit_id: HabitId
    occurrence_key: str
    state: OutcomeState
    occurred_at: Instant
    confirmed_at: Instant | None

    def __post_init__(self) -> None:
        _require_an_occurrence_key(self.occurrence_key)
        object.__setattr__(self, "occurred_at", as_instant(self.occurred_at))
        if self.confirmed_at is not None:
            object.__setattr__(self, "confirmed_at", as_instant(self.confirmed_at))

    @property
    def is_confirmed(self) -> bool:
        """Whether the day this outcome belongs to was confirmed."""
        return self.confirmed_at is not None

    @property
    def is_confirmed_completion(self) -> bool:
        """Whether this row says the content was done, on a day the user confirmed."""
        return self.is_confirmed and self.state in COMPLETION_STATES

    @property
    def is_confirmed_miss(self) -> bool:
        """Whether this row says the content was not done, on a day the user confirmed."""
        return self.is_confirmed and self.state is MISS_STATE


class OutcomeError(DomainError):
    """An outcome names an occurrence no habit key could name."""


def _require_an_occurrence_key(occurrence_key: str) -> None:
    """Refuse a key the one derivation of a habit occurrence key would not produce.

    Checked by re-deriving rather than by describing the shape again: an index is padded in
    exactly one place, :func:`syncr_domain.identity.index_occurrence_key`, and a second
    description here is what would let the two drift. ``'\u0662'`` is the case that makes this
    worth a guard: ``int()`` reads it as 2, so a hand-written check accepts a key no block can
    hold, and the match between an outcome and a block then never fires.
    """
    try:
        index = int(occurrence_key)
    except ValueError as error:
        raise OutcomeError(_not_an_occurrence(occurrence_key)) from error
    if index < 0 or index_occurrence_key(index) != occurrence_key:
        raise OutcomeError(_not_an_occurrence(occurrence_key))


def _not_an_occurrence(occurrence_key: str) -> str:
    return (
        f"an outcome names a habit occurrence by its zero-padded index and {occurrence_key!r} is "
        "not one: a block carrying that key cannot exist, so the row would match nothing"
    )
