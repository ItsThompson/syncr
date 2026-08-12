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

H4 reads the started index too, for the spans rather than for the bindings: what a caller seeded
is the caller's own phase, and a rule that could see nothing else would be blind to time the week
has already begun whenever a caller stated none of it.

**A pin outranks derivation in the immovable index.** A prep or transit block is fixed by
derivation, and the user may still pin one elsewhere, which is how a longer-than-usual commute is
expressed. Composed the other way, that pin would be refused for not being where derivation put
it.

## Every collection is held in one order, and that order lives beside itself

:meth:`PartialPlan.of` sorts each collection through :mod:`syncr_solver.ordering`, which holds one
key per collection and the property they share: every key reads the whole of the value it orders, or
ends in an identity that makes the rest unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from syncr_domain.discretionary import absolute_forbidden, discretionary_intervals
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import IntervalSet, has_started
from syncr_domain.plan import PlanError
from syncr_domain.templates import TemplateEntryKind
from syncr_domain.weeks import local_days
from syncr_solver.ordering import (
    anchor_key,
    area_key,
    frame_key,
    period_key,
    span_key,
    window_key,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from syncr_domain.gaps import ForbiddenWindow
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
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

    **A minimum chunk above the whole is a legal state, and it means the remainder cannot be
    placed.** It is reachable from a valid task: the declared minimum chunk is bounded by the
    ESTIMATE, and ``whole_minutes`` is what is left, so a 120-minute task with a 45-minute minimum
    chunk and 30 minutes to go arrives here. Nothing refuses it, because nothing should: the tail is
    genuinely unplaceable, that is the packing failure the verdict reports, and an approved
    ``accept_partial`` is how it is excused. Clamping the minimum to the remainder would place a
    piece the content says is unusable.
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
    # H10, and H4 for the spans a candidate may not sit on. The bindings whose block has begun, at
    # the span it begun in
    started: Mapping[BindingRef, Held]
    # H11. Every binding the solver may not move, in either sense
    immovable: Mapping[BindingRef, Held]
    # H4 and H12 read this, because each excepts the user's own placement rather than every
    # immovable one: a pin is the one immovable a person chose
    pins: Mapping[BindingRef, Interval]
    # H4, and the per-Area arithmetic H8 and H9 measure. Empty before anything is placed, which
    # is the one field a default can honestly state
    placed: tuple[Placement, ...] = ()
    # The parts of the week an Area may still claim, before any of it is placed. A fact about the
    # SPACE rather than about the placements, so it does not move as candidates are accepted and
    # `with_placed` carries it forward unchanged.
    #
    # A field rather than a call, because H9 asks for it once per candidate and it is the same
    # answer every time: measured on a 152-block week, deriving it per candidate cost 1.1 s of a
    # 2.5 s solve.
    #
    # **It carries no default, and that is not symmetry with the fields above.** An empty claimable
    # set makes H9's free capacity zero, which makes the week read as already short of its floors,
    # which makes the rule return nothing for every candidate: a default would turn a hard
    # constraint into a no-op silently. `of` is the one builder and the one that supplies this.
    claimable: IntervalSet

    def __post_init__(self) -> None:
        object.__setattr__(self, "started", dict(self.started))
        object.__setattr__(self, "immovable", dict(self.immovable))
        object.__setattr__(self, "pins", dict(self.pins))

    @classmethod
    def of(cls, inputs: SolveInputs, *, placed: Sequence[Placement] = ()) -> PartialPlan:
        """The space one week's inputs describe, holding ``placed`` and nothing else.

        ``placed`` is the caller's, because which of the week's existing placements the solver may
        not move is the caller's phase rather than a fact about the inputs: a derivation places
        only what it derives, and a solve carries the past blocks and the pins in as well. H8 and
        H9 measure over what the state holds, so a caller that seeds nothing is asking about a week
        that holds nothing for them. H4 also reads the week's own begun spans, which no caller has
        to state.
        """
        return cls(
            span=inputs.span,
            days=local_days(inputs.iso_week, inputs.zone_by_date, inputs.span),
            frame=tuple(sorted(inputs.frame, key=frame_key)),
            inherited=tuple(sorted(inputs.frame_overhang, key=span_key)),
            anchors=tuple(sorted(inputs.anchors, key=anchor_key)),
            forbidden_windows=tuple(sorted(inputs.forbidden_windows, key=window_key)),
            off_plan=tuple(sorted(inputs.off_plan, key=period_key)),
            areas=tuple(sorted(inputs.areas, key=area_key)),
            started=_started(inputs),
            immovable=_immovable(inputs),
            pins={pin.binding: pin.interval for pin in inputs.pins},
            placed=tuple(placed),
            claimable=_claimable(inputs),
        )

    def with_placed(self, placement: Placement) -> PartialPlan:
        """This state plus one placement, which the next candidate is checked against."""
        return replace(self, placed=(*self.placed, placement))

    def discretionary(self) -> IntervalSet:
        """The parts of the week an Area may still claim, before any of it is placed.

        Read from the field the state was built with rather than derived here, because the answer is
        the same for every candidate a week is offered: see :attr:`claimable`.

        **Kept as a method rather than collapsed into the field**, which is otherwise the reading a
        pass-through invites. Three test modules ask the state this question by name, so collapsing
        it into the field would edit all three.
        """
        return self.claimable

    def holds(self, candidate: Placement) -> bool:
        """Whether the week already holds this candidate's content somewhere, movable or not.

        The two allocation rules read this and nothing else does. Neither has anything to say about
        content the solver cannot place freely: at the span that holds it, refusing would drop a
        block the week already has, and at any OTHER span the refusal belongs to H10 or H11, which
        say the true thing. Step 1 of the algorithm lists the past blocks, the pins and the derived
        blocks as the space rather than as candidates inside it.

        It reads the binding rather than the span for the second of those reasons. Bounded to the
        span, a block dragged off the moment it began was refused with a budget clause: nothing was
        dropped, because H10 refuses the same candidate one row later, but the user who dragged it
        was told about a daily cap.

        The occupancy rules read a narrower exception, the user's own pin at its own span, because a
        derived buffer colliding with another derived buffer IS a refusal a derivation has to make.
        """
        return candidate.binding in self.started or candidate.binding in self.immovable

    def already_netted(self, binding: BindingRef) -> bool:
        """Whether the Area figures arrived with this binding's minutes already subtracted.

        Every placement except one that has started and a pin. That is the set the assembler
        subtracted when it computed ``AreaBudget.floor_minutes`` and ``EligibleTask``'s remaining
        minutes, so a reader netting it a second time counts one minute twice.

        **Two readers, one statement.** H9 asks it of the floor it may still reserve, and the
        objective's deadline term asks it of the work a task still owes. The assembler's own
        statement of the same set is ``syncr_api.plans.netting.Placement.immovable``; a third
        statement here would put the two even further apart.
        """
        return binding in self.started or binding in self.pins


def _claimable(inputs: SolveInputs) -> IntervalSet:
    """The parts of one week an Area may claim, over the same four subtrahends the document takes.

    Stated once, here, so H9's reading of how much room a week has cannot disagree with the figure
    the document reports for the same subtraction.
    """
    return discretionary_intervals(
        inputs.span,
        frame=inputs.frame_occupancy(),
        anchors=IntervalSet(anchor.interval for anchor in inputs.anchors),
        absolute_forbidden=absolute_forbidden(inputs.forbidden_windows),
        off_plan=IntervalSet(period.interval for period in inputs.off_plan),
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
        if has_started(block.interval, inputs.now)
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
