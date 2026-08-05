"""The immovability rules: what the solver may not move, and what it may not intrude on.

H10, H11 and H12. The first two refuse to move a placement the week already holds, and the third
refuses to place anything inside a span the user declared off. All three are here because all three
read the same question about a candidate's binding: is this content already held somewhere, and did
a person put it there.

## H10 and H11 are refusals to MOVE, not refusals to place

Neither can be decided from a candidate alone. Each asks whether the week already holds this
content instance, and refuses a candidate that would put it somewhere else. A candidate at exactly
the interval that holds it is the placement being preserved, so it is accepted.

They are separate rules because they answer to different facts and a reader needs to know which.
H10 is time: a block that has begun cannot be moved because the moment has passed. H11 is authority:
either the user placed it, or derivation determined it. Both are immovable to the solver, and they
differ in everything else, so the checker treats them alike and the reason clause names the sense.

## H12 excepts a pin, and needs no rule of its own for a mostly-off week

A pin inside an off-plan span is honoured. That is how "off, except this one thing" is expressed,
which is why the span carries no per-item affordance: the user pins what survives. The exception is
read from the pin rather than from H11 having already run, so this rule is decidable on its own
whatever order the tuple holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_solver.constraints import Blocked, ConstraintRule

if TYPE_CHECKING:
    from syncr_solver.constraints import Rule
    from syncr_solver.state import PartialPlan, Placement

# What a rejection calls an off-plan span the user gave no name to. A span needs no label to
# suspend scheduling, so most of them have none.
UNNAMED_OFF_PLAN: Final = "a period you declared off"


def past_block(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H10. A block that has started or is in the past stays exactly where it is.

    Decided against the instant the assembly was stamped with, which the state resolved when it was
    built. Without that instant the rule has no reference at all, and reading a clock here would
    make one assembly answer two ways.
    """
    held = state.started.get(candidate.binding)
    if held is None or held.interval == candidate.interval:
        return None
    return Blocked(ConstraintRule.PAST_BLOCK, candidate.interval, held.detail)


def immovable_block(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H11. A pinned block and a block fixed by derivation both stay where they are.

    One rule for both senses, because both are immovable to the solver. The detail names which
    sense, since that is the one thing a reader cannot recover from the rule's own name.
    """
    held = state.immovable.get(candidate.binding)
    if held is None or held.interval == candidate.interval:
        return None
    return Blocked(ConstraintRule.IMMOVABLE_BLOCK, candidate.interval, held.detail)


def off_plan(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H12. Nothing is placed inside a declared off-plan span except a pin.

    The frame is not judged here and needs no exception: whether routines survive the span is the
    user's own choice on the period, resolved before the frame reaches the solver, and the frame is
    the space rather than a candidate inside it.
    """
    if state.pins.get(candidate.binding) == candidate.interval:
        return None
    for period in state.off_plan:
        if period.interval.overlaps(candidate.interval):
            return Blocked(
                ConstraintRule.OFF_PLAN,
                candidate.interval,
                period.label or UNNAMED_OFF_PLAN,
            )
    return None


IMMOVABILITY_RULES: Final[tuple[Rule, ...]] = (past_block, immovable_block, off_plan)
