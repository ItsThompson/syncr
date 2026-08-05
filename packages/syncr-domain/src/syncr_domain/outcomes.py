"""What the outcome log says, which states are a completion, and what each attributes.

The rotation cursor and outstanding debt are both projections of the append-only outcome log.
Neither needs a whole ``BlockOutcome``: they need to know which occurrence of which habit a
row is about, what the user said happened, and whether the day was confirmed. That is what
:class:`HabitOutcome` holds, so the two derivations stay testable with literals and the plan
document's interior stays out of the pure package.

:class:`RecordedOutcome` is the other projection: what the user said happened to one block,
plus the data two of the five states carry. It is what :func:`attributed_span` reads, and it
is where those two required halves are construction invariants rather than only check
constraints, so a row written past the service is refused where it is rebuilt.

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

**Attribution reads the state and not the confirmation.** That exclusion is stated over
reviews and learning, and how many minutes went to a task is neither. A user who says a block
was skipped has said the work was not done, and holding those minutes against the task until
they also settle the day would report progress they explicitly denied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, assert_never

from syncr_domain.errors import DomainError
from syncr_domain.identity import index_occurrence_key
from syncr_domain.intervals import Interval, as_instant

if TYPE_CHECKING:
    from syncr_domain.identifiers import HabitId
    from syncr_domain.identity import BindingRef
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

# The state whose figure the duration-estimate signal is read from, and the state whose span it
# is. Named because three modules state a rule over one of the two and a fourth spelling of
# either is how a rule would come to name a state nothing writes.
MINUTES_STATE: Final = OutcomeState.PARTIAL
INTERVAL_STATE: Final = OutcomeState.MOVED

# A partial completion of no minutes is a skip, which has its own state. The bound is one
# rather than zero so the two states cannot both describe the same event.
MIN_ACTUAL_MINUTES: Final = 1


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
    """An outcome names an occurrence no habit key could name, or omits what its state carries."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordedOutcome:
    """What the user said happened to one block, and the data two of the five states carry.

    Keyed by ``binding`` rather than by a block id, because the binding is what a stored outcome
    denormalizes and what survives its block ceasing to exist. A block id is a digest of the week
    and the binding, so a caller holding one and a caller holding the other are pairing on the
    same identity; the binding is the half that can also be read.

    Both required halves are checked in BOTH directions. A ``partial`` without its minutes
    teaches nothing and claims to, and minutes on a ``completed`` row are a figure no state names
    and no reader would look at, so either would make the pair say two things.
    """

    binding: BindingRef
    state: OutcomeState
    actual_minutes: int | None = None
    actual_interval: Interval | None = None

    def __post_init__(self) -> None:
        _require_the_minutes_only_a_partial_carries(self.state, self.actual_minutes)
        _require_the_interval_only_a_move_carries(self.state, self.actual_interval)


def attributed_span(planned: Interval, outcome: RecordedOutcome | None) -> Interval | None:
    """The span this block contributes to its content's remaining work, or nothing.

    The attribution table, as one function, over the five states and over the absence of a row:

    | State | Contributes |
    |---|---|
    | no row, which is ``presumed`` with no user action | the planned span |
    | ``presumed`` | the planned span |
    | ``completed`` | the planned span |
    | ``partial`` | ``actual_minutes`` from the planned start |
    | ``moved`` | the interval it actually happened in |
    | ``skipped`` | nothing |

    **This is attribution, not capacity.** A caller nets capacity over the block's own interval
    whatever its outcome, because a past span cannot be returned to a capacity window that starts
    at ``now``, and returning one is what would make skipping work improve a verdict.

    ``partial`` yields a PREFIX of the planned span rather than a bare minute count, and ``moved``
    yields the span it really happened in, because every reader of this figure clips it against a
    deadline and against ``now``. A count would have to be placed somewhere before it could be
    clipped, and placing it at the caller would be a second statement of this table. An hour moved
    to after a deadline therefore satisfies that deadline no more than an hour planned there does,
    which is the same rule applied to the span the user gave.

    A ``partial`` reporting more minutes than the block was planned for extends past the planned
    end. That is not refused: the user is reporting how long the work took, and the state they
    chose is theirs.
    """
    if outcome is None:
        return planned
    match outcome.state:
        case OutcomeState.PRESUMED | OutcomeState.COMPLETED:
            return planned
        case OutcomeState.PARTIAL:
            return Interval(planned.start, planned.start + _reported_duration(outcome))
        case OutcomeState.MOVED:
            return outcome.actual_interval
        case OutcomeState.SKIPPED:
            return None
        case _:  # pragma: no cover - the vocabulary is closed and every member is above
            assert_never(outcome.state)


def _reported_duration(outcome: RecordedOutcome) -> timedelta:
    """How long a ``partial`` really took.

    The figure cannot be absent here, because the state and the figure are checked together on
    construction, so this is the type's optionality rather than the value's. Falling back to the
    planned span would be worse than raising: it would silently attribute a block the user said
    ran short at its full length, which is the exact reading this table exists to correct.
    """
    if outcome.actual_minutes is None:  # pragma: no cover - refused on construction
        raise OutcomeError(
            f"a {MINUTES_STATE.value!r} outcome reached attribution with no minutes on it"
        )
    return timedelta(minutes=outcome.actual_minutes)


def _require_the_minutes_only_a_partial_carries(
    state: OutcomeState, actual_minutes: int | None
) -> None:
    """O2, in both directions, because the pair is the sole source of the duration signal."""
    if state is MINUTES_STATE and actual_minutes is None:
        raise OutcomeError(
            f"a {MINUTES_STATE.value!r} outcome states how many minutes it really took: it is the "
            "one source of the duration-estimate signal, and without the figure the row records "
            "that an estimate was wrong without saying by how much"
        )
    if state is not MINUTES_STATE and actual_minutes is not None:
        raise OutcomeError(
            f"only a {MINUTES_STATE.value!r} outcome states its own minutes, and this "
            f"{state.value!r} one states {actual_minutes}: a figure no state names is one no "
            "reader looks at, so it would disagree with the span the block was planned for"
        )
    if actual_minutes is not None and actual_minutes < MIN_ACTUAL_MINUTES:
        raise OutcomeError(
            f"a {MINUTES_STATE.value!r} outcome of {actual_minutes} minutes is a "
            f"{MISS_STATE.value!r} one, which has its own state: the two must not both describe "
            "one event, or the miss policies would read the same block two ways"
        )


def _require_the_interval_only_a_move_carries(
    state: OutcomeState, actual_interval: Interval | None
) -> None:
    """O7's first half, in both directions. The second half is that it creates no pin.

    Where the work really happened is the signal the time-of-day fitness curve is fitted from, so
    a move that does not say when carries no signal at all. The other direction matters for the
    same reason the minutes do: an interval on a state that does not name one would be a second,
    unread answer to when the block happened.
    """
    if state is INTERVAL_STATE and actual_interval is None:
        raise OutcomeError(
            f"a {INTERVAL_STATE.value!r} outcome states the interval it really happened in: that "
            "span is the whole signal, and without it the row says only that the planned hour "
            "was wrong"
        )
    if state is not INTERVAL_STATE and actual_interval is not None:
        raise OutcomeError(
            f"only a {INTERVAL_STATE.value!r} outcome states when it really happened, and this "
            f"{state.value!r} one states {actual_interval.start.isoformat()} to "
            f"{actual_interval.end.isoformat()}: a span no state names is a second answer to "
            "when the block happened"
        )


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
