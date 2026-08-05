"""The thirteen hard constraints in force, in the hard-constraint table's own order.

One place where the vocabulary, the table and the checks meet. :data:`RULE_BY_NAME` pairs each
member of :class:`~syncr_solver.constraints.ConstraintRule` with the function that checks it, and
:data:`HARD_RULES` is that mapping read in the table's order, so what a solve checks is the table
rather than a list somebody kept in step with it.

A member with no entry below fails at import, because the mapping is read by key. A member the
mapping holds and the enum does not cannot be written at all. So the only failure prose could hide
is a rule reporting a member other than its own row's, and a test drives each rule to a rejection
and asserts the member it names.

The rules themselves live beside the question they ask, four modules by what they read: the span
already spent, the shape a block may take, what an Area's budget allows, and what may not move.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_solver.allocation import area_daily_cap, area_floor
from syncr_solver.constraints import HARD_CONSTRAINTS, ConstraintRule
from syncr_solver.immovability import immovable_block, off_plan, past_block
from syncr_solver.occupancy import (
    anchor_overlap,
    block_overlap,
    forbidden_area,
    forbidden_window,
    frame_overlap,
)
from syncr_solver.shape import atomic_not_splittable, below_min_chunk, snap

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_solver.constraints import Rule

RULE_BY_NAME: Final[Mapping[ConstraintRule, Rule]] = {
    ConstraintRule.ANCHOR_OVERLAP: anchor_overlap,
    ConstraintRule.FORBIDDEN_WINDOW: forbidden_window,
    ConstraintRule.FRAME_OVERLAP: frame_overlap,
    ConstraintRule.BLOCK_OVERLAP: block_overlap,
    ConstraintRule.ATOMIC_NOT_SPLITTABLE: atomic_not_splittable,
    ConstraintRule.BELOW_MIN_CHUNK: below_min_chunk,
    ConstraintRule.AREA_DAILY_CAP: area_daily_cap,
    ConstraintRule.AREA_FLOOR: area_floor,
    ConstraintRule.PAST_BLOCK: past_block,
    ConstraintRule.IMMOVABLE_BLOCK: immovable_block,
    ConstraintRule.OFF_PLAN: off_plan,
    ConstraintRule.FORBIDDEN_AREA: forbidden_area,
    ConstraintRule.SNAP: snap,
}

HARD_RULES: Final[tuple[Rule, ...]] = tuple(RULE_BY_NAME[row.rule] for row in HARD_CONSTRAINTS)
"""Every hard constraint, ordered by the table, so a candidate reports the first row it breaks."""
