"""The hard constraints: the closed vocabulary, the table, the state, and the checker.

A plan violating any of the thirteen rules is invalid. The checker answers with **which rule
rejected a candidate and over what window**, because that pair is the ``blocked`` reason clause
the panel renders, and reconstructing it later would mean re-running the check that already
knew.

## The whole vocabulary is here from the start, and only some of it is implemented

:class:`ConstraintRule` names all thirteen rules and :data:`HARD_CONSTRAINTS` is the table, so a
rule that nothing checks yet is added as BEHAVIOUR rather than as vocabulary: a rule function
lands beside the four in :mod:`syncr_solver.occupancy`, and the enum, the table and the reason
clause already speak its name.

Which rules are in force is neither a mode of this module nor a default. :class:`ConstraintCheck`
is constructed with the tuple, so what is being checked is a value at the call site. The rules a
derived plan needs are ``syncr_solver.occupancy.OCCUPANCY_RULES``.

## Two numbers are missing and the gaps are enumerated

H5 and H15 were withdrawn and the numbering is preserved rather than compacted, so existing
references stay valid. :data:`WITHDRAWN_RULES` says why each went, because a missing number
otherwise reads as an omission, and a test crosses the two lists so a rule cannot be both
declared and withdrawn.

## What the space is, and why part of it is never checked

The frame and the anchors are the space rather than candidates inside it. Both are immovable
facts: a routine defines how much time exists and an anchor is time the product does not own,
so two of them overlapping is a state of the week rather than a choice a solve made. They are
placed unchecked and everything else is checked against them, which is the reading of H3 and H4
that lets a routine overlap its own next occurrence and a double-booked calendar keep both
commitments.

## Every ordering key reads the whole of the value it orders

:meth:`PartialPlan.of` sorts each collection, so a candidate overlapping two members names the
earlier one whatever order the inputs arrived in, and a document holds its windows in an order
its inputs cannot change. That holds only while a key can separate two unequal values, so each
key below reads every field its type carries, or ends in an identity that makes the rest
unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from syncr_domain.gaps import ForbiddenWindow
    from syncr_domain.identifiers import AnchorId, AreaId, RoutineId
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.plan import Block
    from syncr_solver.inputs import Anchor, FrameEntry, SolveInputs


class ConstraintRule(StrEnum):
    """One member per hard constraint. The vocabulary a ``blocked`` clause speaks.

    User-visible, so a member with no reachable violation is worse than no member: a property
    test per rule would pass vacuously forever. Every member here has a row in
    :data:`HARD_CONSTRAINTS` and a test asserts the two agree in both directions.
    """

    ANCHOR_OVERLAP = "anchor_overlap"
    FORBIDDEN_WINDOW = "forbidden_window"
    FRAME_OVERLAP = "frame_overlap"
    BLOCK_OVERLAP = "block_overlap"
    ATOMIC_NOT_SPLITTABLE = "atomic_not_splittable"
    BELOW_MIN_CHUNK = "below_min_chunk"
    AREA_DAILY_CAP = "area_daily_cap"
    AREA_FLOOR = "area_floor"
    PAST_BLOCK = "past_block"
    IMMOVABLE_BLOCK = "immovable_block"
    OFF_PLAN = "off_plan"
    FORBIDDEN_AREA = "forbidden_area"
    SNAP = "snap"


@dataclass(frozen=True, slots=True)
class HardConstraint:
    """One row of the hard-constraint table: its number, its name, and what it forbids."""

    number: int
    rule: ConstraintRule
    forbids: str


# The table, in its own numbering. It is data rather than prose so the enum can be crossed
# against it: a rule with no name fails, and a name with no rule fails too.
HARD_CONSTRAINTS: Final[tuple[HardConstraint, ...]] = (
    HardConstraint(1, ConstraintRule.ANCHOR_OVERLAP, "overlapping an imported commitment"),
    HardConstraint(
        2, ConstraintRule.FORBIDDEN_WINDOW, "overlapping a window that forbids every Area"
    ),
    HardConstraint(
        3, ConstraintRule.FRAME_OVERLAP, "overlapping the frame at its effective duration"
    ),
    HardConstraint(
        4, ConstraintRule.BLOCK_OVERLAP, "overlapping a block this solve already placed"
    ),
    HardConstraint(
        6, ConstraintRule.ATOMIC_NOT_SPLITTABLE, "dividing a block that is not splittable"
    ),
    HardConstraint(
        7, ConstraintRule.BELOW_MIN_CHUNK, "a chunk below the minimum its content states"
    ),
    HardConstraint(8, ConstraintRule.AREA_DAILY_CAP, "passing an Area's cap for one day"),
    HardConstraint(
        9, ConstraintRule.AREA_FLOOR, "leaving an Area's floor unmet without a concession"
    ),
    HardConstraint(10, ConstraintRule.PAST_BLOCK, "moving a block that has started or is past"),
    HardConstraint(
        11, ConstraintRule.IMMOVABLE_BLOCK, "moving a pin or a block fixed by derivation"
    ),
    HardConstraint(
        12, ConstraintRule.OFF_PLAN, "placing anything but a pin inside an off-plan span"
    ),
    HardConstraint(13, ConstraintRule.FORBIDDEN_AREA, "a forbidden Area inside a scoped window"),
    HardConstraint(14, ConstraintRule.SNAP, "a start or an end off the fifteen-minute grid"),
)

# Why each withdrawn number is absent. Both were rules that could not fire, so each is now
# either an objective term or a validation on the producer.
WITHDRAWN_RULES: Final[Mapping[int, str]] = {
    5: (
        "a per-block placement window from a strong preference. A hard rule with a conditional "
        "escape is not a hard rule, so a strong window is the costliest component of "
        "time_of_day_misfit instead"
    ),
    15: (
        "never reduce a routine below its minimum duration. No solver operation resizes a "
        "routine: the frame arrives at its effective duration, so this is a validation on the "
        "assembler rather than a constraint"
    ),
}


@dataclass(frozen=True, slots=True)
class Blocked:
    """A candidate window, the rule that rejected it, and what did the rejecting.

    ``window`` is the candidate's own interval rather than the overlap, because that is the span
    the panel renders as tried-and-refused. ``detail`` names the entity, Area, or floor
    responsible, so a reader learns what made the placement impossible rather than only that it
    was.
    """

    rule: ConstraintRule
    window: Interval
    detail: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Placement:
    """A candidate span, and enough of what would sit in it for every rule to judge it.

    The title is here because a rejection names what rejected a candidate, so a placed member of
    the state has to be able to say what it is. The Area is here because two rules read one.
    """

    binding: BindingRef
    interval: Interval
    title: str
    area_id: AreaId | None = None

    @classmethod
    def of(cls, block: Block) -> Placement:
        """The candidate a built block offers, which is the block without its reason.

        A block carries everything a rule reads and a reason besides, so the two are one value
        seen twice rather than two things to keep in step.
        """
        return cls(
            binding=block.binding,
            interval=block.interval,
            title=block.title,
            area_id=block.area_id,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockedCandidate:
    """One rejection, as the log row a solve keeps: what was refused, and by which rule.

    The binding rather than the block, because the block was never placed. The row is bounded by
    the caller that keeps it, so nothing here grows with the number of candidates tried.
    """

    binding: BindingRef
    window: Interval
    rule: ConstraintRule
    detail: str | None = None

    @classmethod
    def of(cls, binding: BindingRef, rejection: Blocked) -> BlockedCandidate:
        """The row a checker's answer becomes, with nothing restated and nothing dropped."""
        return cls(
            binding=binding,
            window=rejection.window,
            rule=rejection.rule,
            detail=rejection.detail,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PartialPlan:
    """What a candidate is checked against: the space the week already spends, and what is placed.

    Every collection is held in span order, so a candidate overlapping two members is rejected by
    naming the earlier one whatever order the inputs arrived in. Without that, permuting an input
    list would change a reason clause while changing no placement.
    """

    frame: tuple[FrameEntry, ...] = ()
    inherited: tuple[Interval, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    forbidden_windows: tuple[ForbiddenWindow, ...] = ()
    placed: tuple[Placement, ...] = ()

    @classmethod
    def of(cls, inputs: SolveInputs) -> PartialPlan:
        """The space one week's inputs describe, with nothing placed in it yet."""
        return cls(
            frame=tuple(sorted(inputs.frame, key=_frame_key)),
            inherited=tuple(sorted(inputs.frame_overhang, key=_span_key)),
            anchors=tuple(sorted(inputs.anchors, key=_anchor_key)),
            forbidden_windows=tuple(sorted(inputs.forbidden_windows, key=_window_key)),
        )

    def with_placed(self, placement: Placement) -> PartialPlan:
        """This state plus one placement, which the next candidate is checked against."""
        return PartialPlan(
            frame=self.frame,
            inherited=self.inherited,
            anchors=self.anchors,
            forbidden_windows=self.forbidden_windows,
            placed=(*self.placed, placement),
        )


type Rule = Callable[[Placement, PartialPlan], Blocked | None]
"""One hard constraint, as the check of it: a rejection, or nothing to report.

Acceptance is the absence of a rejection rather than a value, because there is nothing an
accepted placement has to say. A caller that must not lose a rejection reads ``is not None``.
"""


class ConstraintCheck:
    """The rules a candidate is judged against, held as the tuple a caller chose.

    Which rules are in force is a value rather than a mode, and it carries no default: a caller
    states what it is checking, so a slice adding the remaining nine passes a longer tuple and no
    caller of this class changes.
    """

    __slots__ = ("_rules",)

    def __init__(self, rules: Sequence[Rule]) -> None:
        self._rules = tuple(rules)

    def check(self, candidate: Placement, state: PartialPlan) -> Blocked | None:
        """The first rule ``candidate`` breaks against ``state``, or nothing.

        The first rather than all of them, because the clause budget renders two rejected windows
        per block and each names one rule. Evaluated in the rules' declared order, so the same
        candidate against the same state always reports the same rule.
        """
        for rule in self._rules:
            rejection = rule(candidate, state)
            if rejection is not None:
                return rejection
        return None


def _span_key(interval: Interval) -> tuple[Instant, Instant]:
    """Span order. Instants rather than their text, so two zones' spellings compare as instants."""
    return (interval.start, interval.end)


def _frame_key(entry: FrameEntry) -> tuple[Instant, Instant, str, str, RoutineId]:
    """Span order, ending in the occurrence's own identity so no two entries tie.

    The two fields it does not read, the minimum duration and the flex band, cannot separate two
    entries this key ties: such entries share a routine and an occurrence key, so they are one
    occurrence declared twice, they derive one block id, and a document refuses the pair.
    """
    return (*_span_key(entry.interval), entry.title, entry.occurrence_key, entry.routine_id)


def _anchor_key(anchor: Anchor) -> tuple[Instant, Instant, str, AnchorId]:
    """Span order, the title, then the commitment's identity. Every field an anchor carries."""
    return (*_span_key(anchor.interval), anchor.title, anchor.anchor_id)


# What the window order reads, which is every field a window carries. The anchor is NOT an identity
# here: one commitment casts up to four windows, so two of them can share a span, a label and an
# anchor while differing in kind, in scope, or in the Areas they forbid. A key stopping at the
# anchor would order such a pair by input arrival, and the document holds the windows in this order.
WINDOW_ORDER_FIELDS: Final = (
    "interval",
    "kind",
    "scope",
    "label",
    "forbidden_area_ids",
    "anchor_id",
)


def _window_key(
    window: ForbiddenWindow,
) -> tuple[Instant, Instant, str, str, str, tuple[AreaId, ...], AnchorId]:
    return (
        *_span_key(window.interval),
        window.kind.value,
        window.scope.value,
        window.label,
        window.forbidden_area_ids,
        window.anchor_id,
    )
