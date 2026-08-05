"""The occupancy rules: the four hard constraints a plan derived from nothing else can break.

They are the subset a derived plan needs. It chooses no content, sizes nothing and moves nothing,
so the only way one of its placements can be illegal is that the span is already spent: by an
imported commitment, by a window that forbids every Area, by the circadian frame, or by something
this same pass already placed.

Each rule is a function of a candidate and the state, and each answers with a rejection or with
nothing. They are collected in :data:`OCCUPANCY_RULES` in the hard-constraint table's own order, so
a candidate breaking two of them reports the first row it breaks rather than whichever check
happened to run first.

**Adding the remaining nine is an append here.** The vocabulary, the table, the state and the
checker all live in :mod:`syncr_solver.constraints` and already speak every rule's name, and the
tuple of rules in force is an argument the caller passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_domain.gaps import ForbiddenScope
from syncr_solver.constraints import Blocked, ConstraintRule

if TYPE_CHECKING:
    from syncr_solver.constraints import PartialPlan, Placement, Rule

# What a rejection names when the span that rejected a candidate is a routine occurrence the
# preceding week owns. It carries no title of its own: the week that owns the occurrence holds the
# whole interval and materializes the one block, so this week has the span and not the name.
INHERITED_FRAME: Final = "a routine the preceding week owns"


def anchor_overlap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H1. An anchor is an immovable external fact, so a candidate gives way to it."""
    for anchor in state.anchors:
        if anchor.interval.overlaps(candidate.interval):
            return Blocked(ConstraintRule.ANCHOR_OVERLAP, candidate.interval, anchor.title)
    return None


def forbidden_window(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H2. A window forbidding every Area forbids this candidate whatever Area it carries.

    A window scoped to named Areas is H13's, and it is deliberately not read here: the two
    readings of one window drifting apart is the defect that split the field they arrive in.
    """
    for window in state.forbidden_windows:
        if window.scope is not ForbiddenScope.ALL:
            continue
        if window.interval.overlaps(candidate.interval):
            return Blocked(ConstraintRule.FORBIDDEN_WINDOW, candidate.interval, window.label)
    return None


def frame_overlap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H3. The frame bounds the day, at the effective duration the assembler clamped it to."""
    for entry in state.frame:
        if entry.interval.overlaps(candidate.interval):
            return Blocked(ConstraintRule.FRAME_OVERLAP, candidate.interval, entry.title)
    for span in state.inherited:
        if span.overlaps(candidate.interval):
            return Blocked(ConstraintRule.FRAME_OVERLAP, candidate.interval, INHERITED_FRAME)
    return None


def block_overlap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H4. A solve never creates an overlap, which binds the solve rather than the plan.

    A user-authored overlap and an anchor landing on a planned block are both legitimate contents
    of a week. What this forbids is one placement of this solve overlapping another.
    """
    for placement in state.placed:
        if placement.interval.overlaps(candidate.interval):
            return Blocked(ConstraintRule.BLOCK_OVERLAP, candidate.interval, placement.title)
    return None


# The rules in force for a derived plan, in the table's own order.
OCCUPANCY_RULES: Final[tuple[Rule, ...]] = (
    anchor_overlap,
    forbidden_window,
    frame_overlap,
    block_overlap,
)
