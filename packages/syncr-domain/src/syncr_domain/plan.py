"""The plan document: the blocks a week holds, its figures, and the reason a revision exists.

A revision's document is authoritative and every scalar column beside it is re-derived from
it, so this is the shape the whole plan side of the product is stated over.

**A block is a thing that happens.** It has an interval, content, a reason, and an Area unless
it is the frame or an imported anchor. The two kinds of gap a week can hold are not blocks and
live in :mod:`syncr_domain.gaps`, because what they exist to explain is that nothing is there.

## What a block derives rather than stores

Three values the upstream shape lists as fields are read from the binding instead, because
each would otherwise be a second statement of something already stored.

``id`` is the value six mechanisms pair on, and an id that can be supplied can be supplied
wrongly. There is no field for it and no argument to pass: it is a hash of the week and the
binding, computed on read.

``origin`` and the binding's ``kind`` are two vocabularies for the same seven cases, mapped
bijectively, so either determines the other and neither needs storing twice.

``split_index`` is part of the binding the id is derived from, so a copy on the block could
name a chunk the id does not.

## What this module does not decide

The fifteen-minute grid is not checked here. An imported anchor keeps its real time and the
buffers derived from it are computed from that time, so a block starting at ``:07`` is legal,
and a producer that owes the grid applies it to its own output.

Overlap is not checked either. The solver's own output is overlap-free, but a user-authored
multitask and an anchor landing on a planned block are both legitimate contents of a document.
The constraint binds the solver rather than the plan.

A title is not scrubbed or bounded. It is text a person or a publisher wrote, it reaches a
column with a width, and fitting such text to a column has one home at the boundary that
receives it. A second definition of a whitespace or control-character class here would
diverge from that one the first time either changed, so the only rule stated is that a block
names something: the empty string is refused and nothing else about the text is judged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.discretionary import OccupancyKind
from syncr_domain.errors import DomainError
from syncr_domain.identity import Origin, block_id
from syncr_domain.reasons import require_a_finite_delta

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.gaps import EmptySlot, ForbiddenWindow
    from syncr_domain.identifiers import AreaId, WeekAdjustmentId
    from syncr_domain.identity import BindingRef, BlockId
    from syncr_domain.intervals import Interval
    from syncr_domain.reasons import ReasonRecord
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneId

# The frame is not a category competing with Fitness, and an anchor is time the product does
# not own, so neither carries an Area. Every other origin does, prep and transit included.
ORIGINS_WITHOUT_AN_AREA: Final = frozenset({Origin.FRAME, Origin.ANCHOR})

# A division has at least two chunks. One chunk is the whole task, which is spelled by
# carrying no chunk number at all.
MIN_SPLIT_COUNT: Final = 2

# The owning week has the occurrence but the following week still needs a truthful H3 clause.
INHERITED_FRAME: Final = "a routine the preceding week owns"


@dataclass(frozen=True, slots=True, kw_only=True)
class FrameOverhang:
    """A preceding week's occupied span, with the H3 label and optional Area it carries."""

    interval: Interval
    label: str = INHERITED_FRAME
    area_id: AreaId | None = None

    @property
    def is_circadian_frame(self) -> bool:
        """Whether this inherited span leaves the discretionary-time denominator."""
        return self.area_id is None


# Which kind of span the discretionary-time denominator reads a block of each origin as.
# Total over `Origin`, so a caller assembling the denominator converts a block rather than
# deciding about one, and the subtraction table stays the single home of what each kind does.
#
# `OccupancyKind.SLOT_BLOCK` is deliberately not a value here: a slot's content is bound
# late, so a FILLED slot's block carries the binding of the habit or task that filled it and
# takes that origin. The kind describes the slot, not a block.
_OCCUPANCY_BY_ORIGIN: Final[Mapping[Origin, OccupancyKind]] = {
    Origin.FRAME: OccupancyKind.FRAME,
    Origin.ANCHOR: OccupancyKind.ANCHOR,
    Origin.PREP: OccupancyKind.PREP_BLOCK,
    Origin.TRANSIT: OccupancyKind.TRANSIT_BLOCK,
    Origin.TASK: OccupancyKind.TASK_BLOCK,
    Origin.HABIT: OccupancyKind.HABIT_BLOCK,
    Origin.TEMPLATE_ENTRY: OccupancyKind.TEMPLATE_ENTRY_BLOCK,
}


class PlanError(DomainError):
    """A block or a plan document breaks one of the invariants that make a week readable."""


class RevisionReason(StrEnum):
    """What caused a revision to exist: why a row was appended, not why a block moved.

    ``materialized`` is the template-driven plan before any solving, and
    ``horizon_advanced`` is the maintainer bringing a new week into range. Both are weeks
    nobody has asked for yet, which is why neither is an approval.
    """

    AUTO_APPLIED_FILL = "auto_applied_fill"
    USER_APPROVED = "user_approved"
    TRADEOFF_APPROVED = "tradeoff_approved"
    ANCHOR_DELTA = "anchor_delta"
    MATERIALIZED = "materialized"
    HORIZON_ADVANCED = "horizon_advanced"


class AdjustmentKind(StrEnum):
    """The four concessions an approved tradeoff can persist for one week.

    Here rather than beside the storage table for the same reason ``RevisionReason`` is: the
    week assembler folds a concession into a solve input and a reason clause cites one, so
    both readers are stated over a pure vocabulary and the column's tuple is derived from it.

    Each kind names what its approval modifies, and three of the four modify TWO resolved
    quantities rather than one, because the solver's reading and the probe's reading of one
    concession are separate fields:

    | Kind | What an approval modifies |
    |---|---|
    | ``drop_item`` | the task leaves eligibility, AND every demand naming it goes |
    | ``reduce_routine`` | that routine's effective duration on each named date |
    | ``breach_floor`` | that Area's floor minutes AND its floor reservation |
    | ``accept_partial`` | the task's deadline on its eligibility AND its demands |

    A kind that modified only one of a pair would leave the concession half applied: the
    panel would go quiet while the objective still strained against the excused deadline, or
    the breach would not close the shortfall it was offered for.
    """

    DROP_ITEM = "drop_item"
    REDUCE_ROUTINE = "reduce_routine"
    BREACH_FLOOR = "breach_floor"
    ACCEPT_PARTIAL = "accept_partial"


@dataclass(frozen=True, slots=True, kw_only=True)
class Block:
    """One thing that happens in the week, and why it is where it is.

    ``iso_week`` is a field rather than a value read from the document that holds it, because
    the id is derived from it. A block therefore knows its own identity, and a document
    holding a block from another week is refused rather than silently re-keyed.

    ``pinned`` is TRUE only for the user's own edit. A block whose time was determined by
    derivation -- the frame, a concrete template entry, an anchor, a prep or transit buffer --
    is not pinned, carries no pin glyph, and is not a training label, even though the solver
    may not move it either.

    ``make_up`` says this occurrence was expanded to make an earlier miss good rather than by
    the habit's own cadence. It travels on the block so the outcome recorded against it stores
    the fact, which is what lets a later week's debt derivation tell the discharge from an
    ordinary completion without re-deriving which indexes were debt under a cadence that may
    since have changed.
    """

    iso_week: IsoWeek
    interval: Interval
    binding: BindingRef
    title: str
    reason: ReasonRecord
    area_id: AreaId | None = None
    pinned: bool = False
    superseded_placement: Interval | None = None
    objective_delta: float | None = None
    split_count: int | None = None
    make_up: bool = False

    def __post_init__(self) -> None:
        if not self.title:
            raise PlanError(
                "a block's title is the resolved content name a reader sees on the grid, and "
                "an empty one names nothing. Whether a whitespace-only title names anything "
                "is a question about text, answered where text is fitted to a column"
            )
        _require_an_area_matching_the_origin(self.origin, self.area_id)
        _require_a_pin_to_state_what_it_replaced(
            self.pinned, self.superseded_placement, self.objective_delta
        )
        _require_a_chunk_count_matching_the_chunk(self.split_index, self.split_count)
        _require_a_mark_only_a_habit_occurrence_carries(self.origin, self.make_up)

    @property
    def id(self) -> BlockId:
        """This block's identity, derived on every read from the week and the binding.

        Never stored and never supplied, so it cannot drift from the content it names: there
        is no field to set and no argument to pass.
        """
        return block_id(self.iso_week, self.binding)

    @property
    def origin(self) -> Origin:
        """What this block is to the reader, read from the binding that produced it."""
        return self.binding.origin

    @property
    def split_index(self) -> int | None:
        """Which chunk of a divided task this is, read from the binding the id is derived from."""
        return self.binding.split_index

    @property
    def occupancy_kind(self) -> OccupancyKind:
        """Which kind of span the discretionary-time denominator reads this block as.

        Stated as a mapping into that vocabulary rather than as a second answer to "is this
        subtracted", exactly as :attr:`~syncr_domain.gaps.ForbiddenWindow.occupancy_kind` is:
        the subtraction table has one home, and a caller assembling the four subtrahends asks
        it rather than reading an Area twice.
        """
        return _OCCUPANCY_BY_ORIGIN[self.origin]


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanDocument:
    """One week's plan, in full. Authoritative: every scalar column beside it is derived.

    ``zone_by_date`` is the active zone per day, captured at solve time, so a travel override
    declared later cannot silently re-read a stored week. It covers all seven dates, because a
    day with no zone is a day whose wall times name no instants.

    ``unallocated_minutes`` is discretionary time covered by NO block carrying an Area. It is
    not a residual against Area targets: that expression is exactly zero for a user whose
    percentages sum to 100 and negative for an oversubscribed budget, which is not a
    renderable pie wedge. ``oversubscription_minutes`` is the other quantity, how far the
    targets exceed the time available, and it is zero when they fit.

    ``adjustments`` names the approved concessions this plan was solved under, so a week never
    looks feasible for a reason the user cannot see.
    """

    iso_week: IsoWeek
    zone_by_date: Mapping[Date, ZoneId]
    discretionary_minutes: int
    unallocated_minutes: int
    oversubscription_minutes: int
    blocks: tuple[Block, ...] = ()
    frame_overhang: tuple[FrameOverhang, ...] = ()
    forbidden_windows: tuple[ForbiddenWindow, ...] = ()
    empty_slots: tuple[EmptySlot, ...] = ()
    adjustments: tuple[WeekAdjustmentId, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_by_date", dict(self.zone_by_date))
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "frame_overhang", tuple(self.frame_overhang))
        object.__setattr__(self, "forbidden_windows", tuple(self.forbidden_windows))
        object.__setattr__(self, "empty_slots", tuple(self.empty_slots))
        object.__setattr__(self, "adjustments", tuple(self.adjustments))
        require_a_zone_for_every_day(self.iso_week, self.zone_by_date)
        _require_blocks_of_this_week(self.iso_week, self.blocks)
        _require_figures_that_count_minutes(
            self.discretionary_minutes, self.unallocated_minutes, self.oversubscription_minutes
        )

    def blocks_by_id(self) -> Mapping[BlockId, Block]:
        """This week's blocks by their derived ids, which is what a diff pairs on.

        Ids are unique within a document by construction, so the mapping loses nothing and a
        caller comparing two documents needs no lookup of any kind.
        """
        return {block.id: block for block in self.blocks}


def _require_an_area_matching_the_origin(origin: Origin, area_id: AreaId | None) -> None:
    """B2, in both directions, so neither half can be satisfied while the other is broken.

    The frame defines how much time exists rather than competing for it, and an anchor is time
    the product does not own. A prep or transit block DOES carry an Area, the one its anchor
    type named, which is what makes it consume discretionary time the way a task does.
    """
    carries_an_area = origin not in ORIGINS_WITHOUT_AN_AREA
    if carries_an_area == (area_id is not None):
        return
    if carries_an_area:
        raise PlanError(
            f"a {origin.value!r} block carries an Area: it consumes discretionary time, so "
            "without one its minutes would be charged to nothing"
        )
    raise PlanError(
        f"a {origin.value!r} block carries no Area: the frame defines how much time exists "
        "rather than competing for it, and an anchor is time the product does not own"
    )


def _require_a_pin_to_state_what_it_replaced(
    pinned: bool, superseded_placement: Interval | None, objective_delta: float | None
) -> None:
    """B1, in both directions, because the pair is what the reason panel renders from.

    A pin without them would send the panel walking the edit log, and either of them without a
    pin would render a counterfactual nobody chose.
    """
    stated = superseded_placement is not None and objective_delta is not None
    if pinned and not stated:
        raise PlanError(
            "a pinned block states the placement it replaced and what replacing it cost: the "
            "reason panel renders both from the block rather than by walking the edit log"
        )
    if not pinned and (superseded_placement is not None or objective_delta is not None):
        raise PlanError(
            "only a pinned block replaced a placement: a block fixed by derivation was never "
            "moved off one, so a superseded placement here would render a choice nobody made"
        )
    if objective_delta is not None:
        require_a_finite_delta(objective_delta)


def _require_a_chunk_count_matching_the_chunk(
    split_index: int | None, split_count: int | None
) -> None:
    """A chunk states which of how many, or the block is the whole task.

    The index comes from the binding, because the id is derived from it. The count is the
    block's own, and the two travel together: chunk 2 with no count renders "2 of nothing".
    """
    if (split_index is None) != (split_count is None):
        missing = "no count" if split_count is None else "no index"
        raise PlanError(
            f"a chunk states which of how many, and this one states {missing}: a divided task "
            "renders '2 of 3', so half the pair renders half the label"
        )
    if split_count is None or split_index is None:
        return
    if split_count < MIN_SPLIT_COUNT:
        raise PlanError(
            f"a divided task has at least {MIN_SPLIT_COUNT} chunks and this one claims "
            f"{split_count}: one chunk is the whole task, which carries no chunk number at all"
        )
    if not 0 <= split_index < split_count:
        raise PlanError(
            f"chunk {split_index} of {split_count} does not exist: chunks are numbered from "
            "zero, so the last one is one below the count"
        )


def _require_a_mark_only_a_habit_occurrence_carries(origin: Origin, make_up: bool) -> None:
    """A make-up mark states something about a habit's expansion, and about nothing else.

    Every other origin has no expansion to fall behind on, so a mark on one is a row no
    assembler wrote and a figure downstream would read as debt that never existed.
    """
    if make_up and origin is not Origin.HABIT:
        raise PlanError(
            f"only a habit occurrence can be a made-up one, and this block is a {origin.value}: "
            "the mark names an occurrence the week's expansion added for an earlier miss, and "
            "no other kind of block is expanded"
        )


def require_a_zone_for_every_day(iso_week: IsoWeek, zone_by_date: Mapping[Date, ZoneId]) -> None:
    """Exactly the week's seven dates, no more and no fewer.

    A missing day is a day whose wall times resolve against nothing, which is how a travel
    override taken mid-week silently reads the wrong offset. A foreign date is a day this
    document does not describe.

    Public, because a plan document is not the only shape that carries the mapping: a solve
    input carries the same one for the same reason, and a second statement of the rule is
    how the two would come to accept different sets.
    """
    dates = set(iso_week.dates())
    missing = [str(day) for day in iso_week.dates() if day not in zone_by_date]
    foreign = sorted(str(day) for day in zone_by_date if day not in dates)
    stated = ", ".join(filter(None, (_named("leaves out", missing), _named("names", foreign))))
    if stated:
        raise PlanError(
            f"a plan document states the active zone for each of {iso_week}'s seven days, and "
            f"this one {stated}: a day with no zone resolves its wall times against nothing"
        )


def _named(verb: str, days: list[str]) -> str:
    return f"{verb} {', '.join(days)}" if days else ""


def _require_blocks_of_this_week(iso_week: IsoWeek, blocks: tuple[Block, ...]) -> None:
    """One week per document, and one block per identity inside it.

    Both halves protect the same thing. A block from another week carries an id derived
    against that week, and two blocks sharing an identity would make the pairing a diff
    performs ambiguous: the first would be found and the second would be invisible.
    """
    foreign = sorted({str(block.iso_week) for block in blocks if block.iso_week != iso_week})
    if foreign:
        raise PlanError(
            f"a plan document holds one week's blocks and this one for {iso_week} holds blocks "
            f"of {', '.join(foreign)}: an id is derived against the week, so a block from "
            "another one names nothing here"
        )
    seen: set[BlockId] = set()
    for block in blocks:
        if block.id in seen:
            raise PlanError(
                f"two blocks share the identity {block.binding.kind.value!r} "
                f"{block.binding.entity_id} occurrence {block.binding.occurrence_key!r}: one "
                "binding produces one block per week, so a diff would pair the first and never "
                "see the second"
            )
        seen.add(block.id)


def _require_figures_that_count_minutes(
    discretionary_minutes: int, unallocated_minutes: int, oversubscription_minutes: int
) -> None:
    """B8, and the two figures beside it that count the same way.

    Each measures minutes, so none is negative. Unallocated time is discretionary time no
    block covered, so it cannot exceed the discretionary time it is part of; the earlier
    definition as a residual against Area targets could go negative, which is what makes this
    worth checking rather than assuming.
    """
    negative = {
        name: value
        for name, value in (
            ("discretionary_minutes", discretionary_minutes),
            ("unallocated_minutes", unallocated_minutes),
            ("oversubscription_minutes", oversubscription_minutes),
        )
        if value < 0
    }
    if negative:
        stated = ", ".join(f"{name}={value}" for name, value in sorted(negative.items()))
        raise PlanError(
            f"a plan document's figures count minutes, so none of these is negative: {stated}"
        )
    if unallocated_minutes > discretionary_minutes:
        raise PlanError(
            f"{unallocated_minutes} unallocated minutes is more than the "
            f"{discretionary_minutes} discretionary minutes it is part of: unallocated time is "
            "discretionary time no block carrying an Area covered, not a residual against "
            "Area targets"
        )
