"""The sealed twelve-step Area ramp, and the order an Area is dealt a step from it.

A pigment is **assigned, never picked**. No colour picker exists anywhere in the product,
so the only question this module answers is which step the next Area takes.

The ramp itself lives in `frontend/src/tokens/primitives.css`, which holds the twelve inks
and their measured contrast, and `docs/design/specimen.html` computes the hue ledger that
verifies the deal order below. Nothing here names an ink: a step is an index, and which
colour that index renders as is the token layer's alone. A second statement of the inks in
Python would be a second source of truth for the visual language.

**The deal order is not numeric order.** Areas take steps in the order
``01, 05, 08, 10, 03, 07, 12, 06, 02, 04, 09, 11`` (one-based, as the tokens are named),
which is what gives a user with four Areas four pigments at least 75 degrees apart in hue.
The order does not defer the ramp's tightest adjacent pairs and is not what separates
them: a pair is separated by carrying different hatches and different Area names, and by
the inks having been respaced so the tightest gap is 19.4 degrees.

**Past twelve Areas the ramp repeats**, and identity then rests on the hatch and the Area
name. That is stated to the user rather than prevented, because a thirteenth Area is a
legitimate thing to declare and a thirteenth ink is not a legitimate thing to invent.
"""

from __future__ import annotations

from typing import Final

from syncr_domain.errors import DomainError

type PigmentIndex = int

# The ramp is sealed at twelve. Adding a step is a change to the design language, not to
# this constant.
PIGMENT_COUNT: Final = 12

# Zero-based indices into the ramp, in the order Areas are dealt. A permutation of every
# step, which is what makes the twelfth Area the last one to receive an unused pigment.
PIGMENT_DEAL_ORDER: Final[tuple[PigmentIndex, ...]] = (0, 4, 7, 9, 2, 6, 11, 5, 1, 3, 8, 10)

# How many Areas are dealt an unused pigment before the ramp starts repeating.
FIRST_FOUR_DEALT: Final = 4


class PigmentError(DomainError):
    """A value names no step of the ramp."""


def require_pigment_index(value: int) -> PigmentIndex:
    """``value`` as a step of the ramp, or a rejection naming the range.

    The bound is checked here rather than at each caller so the wire, the database, and
    the deal all reject the same values.
    """
    if not 0 <= value < PIGMENT_COUNT:
        raise PigmentError(
            f"{value} is not a step of the ramp, which holds {PIGMENT_COUNT} steps "
            f"indexed 0 to {PIGMENT_COUNT - 1}"
        )
    return value


def next_pigment_index(assigned_count: int) -> PigmentIndex:
    """The step the next Area takes, given how many Areas already hold one.

    Wraps at twelve, so the thirteenth Area takes the first step again. Counting Areas
    rather than tracking a cursor means the answer follows from the rows that exist.
    """
    return PIGMENT_DEAL_ORDER[_require_a_count(assigned_count) % PIGMENT_COUNT]


def is_ramp_exhausted(assigned_count: int) -> bool:
    """Whether the next Area will reuse a step another Area already holds."""
    return _require_a_count(assigned_count) >= PIGMENT_COUNT


def _require_a_count(assigned_count: int) -> int:
    if assigned_count < 0:
        raise PigmentError(f"{assigned_count} Areas is not a count")
    return assigned_count
