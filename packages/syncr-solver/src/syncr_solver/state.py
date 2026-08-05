"""What a candidate placement is, and the state of the week every rule judges it against.

Two values and one rule of composition. :class:`Placement` is a candidate: a span, and enough of
what would sit in it for each of the thirteen hard constraints to decide. :class:`PartialPlan` is
the week as the checker sees it: the space already spent, the figures an Area's budget allows, the
bindings the solver may not move, and what this pass has placed so far.

## The space, and the candidates inside it

The frame and the anchors are the space rather than candidates. Both are immovable facts, so two
of them overlapping is a state of the week rather than a choice a solve made: a routine of more
than a local day overlaps its own next occurrence, and a double-booked calendar keeps both
commitments. A caller places them unchecked and offers everything derived from them here.

## Every field names the rule that reads it

A field nothing reads is a rule that cannot fire, and a rule reading a field the caller left
empty passes vacuously. So no field carries a default except ``placed``, which is empty by
definition before anything is placed, and each is annotated with its reader.

## Three indexes by binding, because three rules ask about one content instance

H10 asks whether this content already holds a span that has begun, H11 whether it is held
somewhere at all, and H4 and H12 whether this candidate IS the user's own placement. Each is a
lookup by :class:`~syncr_domain.identity.BindingRef` rather than a scan, so no ordering decides
the answer and one binding has one answer.

**A pin outranks derivation in the immovable index.** A prep or transit block is fixed by
derivation, and the user may still pin one elsewhere, which is how a longer-than-usual commute is
expressed. Composed the other way, that pin would be refused for not being where derivation put
it.

## Every ordering key reads the whole of the value it orders

Each collection is sorted, so a candidate overlapping two members names the earlier one whatever
order the inputs arrived in, and a document holds its windows in an order its inputs cannot
change. That holds only while a key can separate two unequal values, so each key below reads
every field its type carries, or ends in an identity that makes the rest unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from syncr_domain.discretionary import absolute_forbidden, discretionary_intervals
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import IntervalSet
from syncr_domain.plan import PlanError
from syncr_domain.templates import TemplateEntryKind
from syncr_domain.weeks import local_days
from syncr_solver.inputs import frame_occupancy

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from syncr_domain.gaps import ForbiddenWindow
    from syncr_domain.identifiers import AnchorId, AreaId, RoutineId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.off_plan import OffPlanPeriod
    from syncr_domain.plan import Block
    from syncr_domain.weeks import LocalDay
    from syncr_solver.inputs import Anchor, AreaBudget, FrameEntry, SolveInputs

# The two kinds of content whose size the solver chooses. A task is divided and re-sized as work
# is placed; a habit occurrence is sized within its elastic range. Every other kind arrives at a
# span derivation determined, so there is nothing for a sizing rule to read.
SIZED_KINDS: Final = frozenset({BindingKind.TASK, BindingKind.HABIT})

# The senses in which a binding is held, as the words a rejection uses. One rule reports both,
# because both are immovable to the solver; they differ in everything else.
PINNED: Final = "pinned"
FIXED_BY_DERIVATION: Final = "fixed by derivation"

# What a rejection calls a pinned binding no input names a title for. A pin is a placement rather
# than content, so a week whose live plan does not hold the block has nothing to call it.
UNNAMED_PIN: Final = "a block you pinned"


@dataclass(frozen=True, slots=True, kw_only=True)
class Sizing:
    """How much of one demand a candidate places, and whether the demand may be divided.

    ``whole_minutes`` is what placing all of what is left would take: a task's remaining minutes,
    or an occurrence's smallest legal length. ``min_chunk_minutes`` is the smallest piece a
    divisible demand may be placed in, and it is read only when ``splittable`` is true, because an
    atomic demand is this duration or nothing rather than a duration with a floor.
    """

    whole_minutes: int
    min_chunk_minutes: int
    splittable: bool

    def __post_init__(self) -> None:
        counted = {
            "whole_minutes": self.whole_minutes,
            "min_chunk_minutes": self.min_chunk_minutes,
        }
        stated = ", ".join(f"{name}={value}" for name, value in counted.items() if value < 1)
        if stated:
            raise PlanError(
                f"a sizing counts the minutes a demand takes, so neither is below one: {stated}. "
                "A demand of no minutes is a demand nothing has to place"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class Placement:
    """A candidate span, and enough of what would sit in it for every rule to judge it.

    The title is here because a rejection names what rejected a candidate, so a placed member of
    the state has to be able to say what it is. The Area is here because four rules read one.

    ``sizing`` is present for exactly the two kinds whose size the solver chooses, in both
    directions. A task or an occurrence arriving without one would escape the two rules about how
    small a block may be; anything else carrying one would claim a choice derivation already made.
    """

    binding: BindingRef
    interval: Interval
    title: str
    area_id: AreaId | None = None
    sizing: Sizing | None = None

    def __post_init__(self) -> None:
        _require_a_sizing_matching_the_kind(self.binding.kind, self.sizing)

    @classmethod
    def of(cls, block: Block, *, sizing: Sizing | None = None) -> Placement:
        """The candidate a built block offers, which is the block without its reason.

        A block carries everything a rule reads except how much of a demand it places, so the two
        are one value seen twice rather than two things to keep in step. The sizing is the
        caller's, because it is the choice the caller is asking about.
        """
        return cls(
            binding=block.binding,
            interval=block.interval,
            title=block.title,
            area_id=block.area_id,
            sizing=sizing,
        )

    def minutes(self) -> int:
        """The whole minutes this candidate would occupy."""
        return self.interval.total_minutes()


@dataclass(frozen=True, slots=True, kw_only=True)
class Held:
    """A binding the solver may not place freely: where it is held, and what holds it."""

    interval: Interval
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PartialPlan:
    """What a candidate is checked against: the week's own spans, and what is placed in it."""

    # The week's TRUE elapsed span. H9 measures free capacity inside it
    span: Interval
    # Each date as the span the user really had, so a daily cap is measured on a 23-hour date as
    # 23 hours. Already in the week's date order, which `local_days` derives forward
    days: tuple[LocalDay, ...]
    # H3, and H11 for a routine occurrence
    frame: tuple[FrameEntry, ...]
    # H3. The preceding week's occurrences as the spans they occupy here, which carry no title
    inherited: tuple[Interval, ...]
    # H1, and H11 for an imported commitment
    anchors: tuple[Anchor, ...]
    # H2 for the windows that forbid every Area, H13 for the ones that name some
    forbidden_windows: tuple[ForbiddenWindow, ...]
    # H12
    off_plan: tuple[OffPlanPeriod, ...]
    # H8 reads the daily cap, H9 the floor still to reserve
    areas: tuple[AreaBudget, ...]
    # H10. The bindings whose block has begun, at the span it begun in
    started: Mapping[BindingRef, Held]
    # H11. Every binding the solver may not move, in either sense
    immovable: Mapping[BindingRef, Held]
    # H4 and H12 read this, because each excepts the user's own placement rather than every
    # immovable one: a pin is the one immovable a person chose
    pins: Mapping[BindingRef, Interval]
    # H4, and the per-Area arithmetic H8 and H9 measure. Empty before anything is placed, which
    # is the one field a default can honestly state
    placed: tuple[Placement, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "started", dict(self.started))
        object.__setattr__(self, "immovable", dict(self.immovable))
        object.__setattr__(self, "pins", dict(self.pins))

    @classmethod
    def of(cls, inputs: SolveInputs, *, placed: Sequence[Placement] = ()) -> PartialPlan:
        """The space one week's inputs describe, holding ``placed`` and nothing else.

        ``placed`` is the caller's, because which of the week's existing placements the solver may
        not move is the caller's phase rather than a fact about the inputs: a derivation places
        only what it derives, and a solve carries the past blocks and the pins in as well. H4, H8
        and H9 measure over what the state holds, so a caller that seeds nothing is asking about a
        week that holds nothing.
        """
        return cls(
            span=inputs.span,
            days=local_days(inputs.iso_week, inputs.zone_by_date, inputs.span),
            frame=tuple(sorted(inputs.frame, key=_frame_key)),
            inherited=tuple(sorted(inputs.frame_overhang, key=_span_key)),
            anchors=tuple(sorted(inputs.anchors, key=_anchor_key)),
            forbidden_windows=tuple(sorted(inputs.forbidden_windows, key=_window_key)),
            off_plan=tuple(sorted(inputs.off_plan, key=_period_key)),
            areas=tuple(sorted(inputs.areas, key=_area_key)),
            started=_started(inputs),
            immovable=_immovable(inputs),
            pins={pin.binding: pin.interval for pin in inputs.pins},
            placed=tuple(placed),
        )

    def with_placed(self, placement: Placement) -> PartialPlan:
        """This state plus one placement, which the next candidate is checked against."""
        return replace(self, placed=(*self.placed, placement))

    def discretionary(self) -> IntervalSet:
        """The parts of the week an Area may still claim, before any of it is placed.

        A fact about the space rather than about the placements, so it does not move as candidates
        are accepted: what claims it is measured separately, against this. It is the same
        arithmetic and the same four subtrahends the document's own denominator is taken over, so
        H9's reading of how much room a week has cannot disagree with the figure it reports.
        """
        return discretionary_intervals(
            self.span,
            frame=frame_occupancy(self.frame, self.inherited),
            anchors=IntervalSet(anchor.interval for anchor in self.anchors),
            absolute_forbidden=absolute_forbidden(self.forbidden_windows),
            off_plan=IntervalSet(period.interval for period in self.off_plan),
        )

    def claimed(self, area_id: AreaId, *, including: Placement | None = None) -> IntervalSet:
        """The spans this Area's placements cover, unioned so a minute claimed twice counts once.

        Unioned rather than summed, which is what keeps a user-authored overlap inside one Area
        from reading as twice the time: two blocks over one hour occupy one hour of the day. The
        solver's own placements never overlap, because H4 forbids it, so the two readings differ
        only where the user has already overlapped something by hand.
        """
        offered = () if including is None else (including,)
        return IntervalSet(
            placement.interval
            for placement in (*self.placed, *offered)
            if placement.area_id == area_id
        )


def _require_a_sizing_matching_the_kind(kind: BindingKind, sizing: Sizing | None) -> None:
    """The two kinds the solver sizes carry a sizing, and the five it does not carry none.

    Both halves protect a rule from passing vacuously. A task or an occurrence with no sizing
    escapes both rules about how small a block may be, and derivation's own placements carrying
    one would invite a rule to re-decide a length nobody chose.
    """
    sized = kind in SIZED_KINDS
    if sized == (sizing is not None):
        return
    if sized:
        raise PlanError(
            f"a {kind.value!r} candidate states how much of its demand it places: the solver "
            "chooses that length, and without it nothing can refuse a block below the minimum"
        )
    raise PlanError(
        f"a {kind.value!r} candidate states no sizing: derivation determined its span, so a "
        "minimum chunk here would name a division of something that has none"
    )


def _started(inputs: SolveInputs) -> Mapping[BindingRef, Held]:
    """Every binding the live plan holds at a span that has begun, decided against ``inputs.now``.

    ``now`` is stamped by the assembler from its own argument rather than read from a clock, so
    which blocks have begun is a fact about the assembly and an assembly is reproducible. Without
    it the rule has no reference instant at all.
    """
    return {
        block.binding: Held(interval=block.interval, detail=block.title)
        for block in _live(inputs)
        if block.interval.start <= inputs.now
    }


def _immovable(inputs: SolveInputs) -> Mapping[BindingRef, Held]:
    """Every binding the solver may not move, and the span that holds it.

    Derivation first and the pins last, so a pin outranks the span derivation chose: the user may
    pin a prep or transit block elsewhere, and composed the other way that pin would be refused
    for not being where it was derived.
    """
    derived = {binding: (interval, title) for binding, interval, title in _fixed(inputs)}
    named = {
        **{block.binding: block.title for block in _live(inputs)},
        **{binding: title for binding, (_, title) in derived.items()},
    }
    held = {
        binding: Held(interval=interval, detail=f"{title}, {FIXED_BY_DERIVATION}")
        for binding, (interval, title) in derived.items()
    }
    for pin in inputs.pins:
        held[pin.binding] = Held(
            interval=pin.interval,
            detail=f"{named.get(pin.binding, UNNAMED_PIN)}, {PINNED}",
        )
    return held


def _live(inputs: SolveInputs) -> tuple[Block, ...]:
    """The blocks the week's current plan holds, or none because it has no plan yet."""
    return () if inputs.live_plan is None else inputs.live_plan.blocks


def _fixed(inputs: SolveInputs) -> Iterator[tuple[BindingRef, Interval, str]]:
    """Every binding whose span derivation determined, with the span and the name it renders.

    Four kinds, which is the enumeration the second sense of immovable gives: the circadian frame,
    the imported commitments, the buffers their types cast, and the concrete entries of each day's
    shape. A slot is not among them, because its content binds late and no block exists yet to be
    held anywhere.

    Each binding is spelled by the struct that owns it rather than rebuilt here, so the identity a
    rejection names is the identity the block will carry.
    """
    for entry in inputs.frame:
        yield (entry.block_binding, entry.interval, entry.title)
    for anchor in inputs.anchors:
        yield (BindingRef.for_anchor(anchor.anchor_id), anchor.interval, anchor.title)
    for shadow in inputs.shadow_blocks:
        yield (shadow.binding, shadow.interval, shadow.title)
    for materialized in inputs.template_entries:
        if materialized.kind is TemplateEntryKind.CONCRETE and materialized.title:
            yield (materialized.block_binding, materialized.interval, materialized.title)


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


def _period_key(period: OffPlanPeriod) -> tuple[Instant, Instant, bool, bool, str]:
    """Span order, then what survives inside the span and the user's word for it.

    The span alone is already total over a legal input, because two periods of one tenant never
    cover a common instant. The rest of the value is read anyway, so the order does not rest on an
    invariant this module does not check, and a period with no label is separated from one whose
    label is empty rather than tying with it.
    """
    return (
        *_span_key(period.interval),
        period.keep_frame,
        period.label is None,
        period.label or "",
    )


def _area_key(area: AreaBudget) -> AreaId:
    """The Area's own identity, which makes every other field it carries unreachable as a tie.

    One budget per Area per week, so two budgets sharing an identity are one Area declared twice
    and their figures would disagree about the same Area.
    """
    return area.area_id


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
