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

    ``occurrence_key`` is the occurrence's index within its week, assigned by the week
    assembler in expansion order and carried on the outcome's binding. Neither derivation
    reads it: it is here because it is what identifies WHICH occurrence a correction
    corrected, and a projection that dropped it could not be built from a binding.
    """

    habit_id: HabitId
    occurrence_key: str
    state: OutcomeState
    occurred_at: Instant
    confirmed_at: Instant | None

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
