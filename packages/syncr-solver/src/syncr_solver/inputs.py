"""``SolveInputs``: everything a solve reads, already resolved, plus its member types.

The solver performs no lookups, derives no domain projection, and reads no clock. Every
figure it needs arrives on this struct, which is what lets the placement code and the
feasibility probe be tested against literals. The component that fills it is the week
assembler in the api package, and everything the solver does not do lands there.

## Two consumers, and the field pairs that exist because of them

This struct serves the solver and, through ``for_probe()``, the feasibility probe. Both
ask "how much of this is left", and **they need different answers**, because the solver
discards and re-places an unpinned future block while the probe's free capacity has
already subtracted it. Collapsing either pair into one field is the defect this module is
shaped to prevent, and it has been found three times on three different fields.

```
                     THE SOLVER reads            THE PROBE reads
work still to do     EligibleTask                DeadlineDemand
                       .remaining_minutes          .remaining_minutes
floor to reserve     AreaBudget                  AreaBudget
                       .floor_minutes              .floor_reservation_minutes

nets                 the attributed span of      EVERY placement, pinned or not,
                     every immovable placement,  past or future
                     clipped at ``now``: what
                     was done of each block the
                     solver cannot re-place

why                  it DISCARDS and re-places   its `free` already subtracts every
                     unpinned future blocks,     placement, so a quantity netting a
                     so netting them would       narrower set counts a different set
                     leave the work short        on each side of one comparison
```

**If the solver read the probe's number:** a 4h task with 2h placed unpinned yields 2h,
the solver places 2h, the task is scheduled at half its size, and because both sides
agree nothing reports a shortfall. **If the probe read the solver's number:** `free`
subtracts that 2h block while the demand does not, so it reports a 2h shortfall the week
does not have. Any future change that makes a pair look redundant belongs against those
two failures first.

``DeadlineDemand`` is not derivable from anything else here: it needs a task's estimate
and its recorded minutes, and neither appears on this struct. That is why the assembler
computes it directly rather than ``for_probe()`` projecting it out of ``eligible_tasks``.

## One field that is two fields for a different reason, so it is not mistaken for a pair

``frame_overhang`` is not a second quantity. Both consumers read it as the same thing the
field above it is: occupied time, subtracted for one reason. It is separate from ``frame``
because one week OWNS a boundary-crossing occurrence and materializes its block, so the
week it runs into carries the spans without carrying the occurrence. ``frame_occupancy()``
is the one reading of the two together, which is what keeps this pair from becoming the
kind above.

## What is deliberately absent

No identifier of the tenant, because a snapshot is already one tenant's. No clock: ``now``
is stamped by the assembler from its own argument, so an assembly is reproducible and a
caller can assemble against a past instant when reproducing a failure. No ``max_per_day``
on ``ResolvedPreference``: the cap is an Area's and travels on ``AreaBudget``, so no
override can relax a hard cap. And no minted values: ``seed`` is derived on read for the
same reason a block's id is, since a value that can be supplied can be supplied wrongly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

# ``DeadlineDemand`` is defined beside the probe that reads it, and re-exported here so a reader
# of this struct's fields finds the type next to them. The redundant alias is the explicit
# re-export form: an implicit one is invisible to a strict type checker.
from syncr_domain.feasibility import DeadlineDemand as DeadlineDemand
from syncr_domain.feasibility import FloorReservation, ProbeInputs, ScopedWindow
from syncr_domain.gaps import EmptySlot, ForbiddenScope

# Re-exported for the same reason ``DeadlineDemand`` is: a reader of ``HabitOccurrence``'s
# fields finds the vocabulary its binding source speaks next to them. The redundant alias is the
# explicit re-export form, and the runtime import is what makes the re-export reachable.
from syncr_domain.habits import BindingSource as BindingSource  # noqa: TC001
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import IntervalSet, as_instant
from syncr_domain.plan import PlanError, require_a_zone_for_every_day
from syncr_domain.templates import TemplateEntryKind
from syncr_solver.churn_baseline import ChurnBaseline as ChurnBaseline

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_domain.gaps import ForbiddenWindow
    from syncr_domain.habits import Duration
    from syncr_domain.identifiers import (
        AnchorId,
        AreaId,
        RoutineId,
        TemplateEntryId,
        WeekAdjustmentId,
    )
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.off_plan import OffPlanPeriod
    from syncr_domain.plan import AdjustmentKind, PlanDocument
    from syncr_domain.preferences import PreferenceOwner, PreferenceStrength
    from syncr_domain.tasks import Priority
    from syncr_domain.templates import BindingTarget
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneId

# How many bytes of the identity digest the seed takes. Eight gives a 64-bit integer,
# which is the width a caller can hand to any generator without truncating it further.
_SEED_BYTES = 8


@dataclass(frozen=True, slots=True, kw_only=True)
class FrameEntry:
    """One routine's occurrence on one local date: the circadian frame, resolved.

    ``interval`` is at the EFFECTIVE duration, which is the target duration less any
    approved reduction, clamped to ``min_duration_minutes``. The clamp is a domain
    validation on the assembler rather than a solver constraint, because no solver
    operation resizes a routine: the frame defines the search space rather than competing
    inside it.

    ``min_duration_minutes`` travels with the entry because it is what the clamp was
    applied against, so a tradeoff enumerator can ask how much give is left without
    reading the routine row again.
    """

    routine_id: RoutineId
    occurrence_key: str
    interval: Interval
    min_duration_minutes: int
    flex_band_minutes: int
    title: str

    @property
    def block_binding(self) -> BindingRef:
        """The identity the block this occurrence materializes into carries.

        Spelled here rather than at each reader, because two of them exist: the module that builds
        the block, and the checker's index of what the solver may not move. A second spelling would
        let the identity a rejection names differ from the identity the block takes.
        """
        return BindingRef(BindingKind.ROUTINE, self.routine_id, self.occurrence_key)


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryBinding:
    """The content a concrete template entry names: a routine, or a habit.

    Two fields rather than a ``BindingRef``, and the reason is the occurrence key. A
    habit's binding is keyed by its position in the week's expansion, and which of a
    habit's occurrences a concrete entry claims is decided when content is bound rather
    than when the entry materializes. So this names the ENTITY, and the block's own
    identity is derived from the entry's id and date instead.
    """

    target: BindingTarget
    entity_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializedEntry:
    """One template entry, resolved for one local date.

    ``occurrence_key`` is that date: five ``Shower`` blocks in a week need five
    identities, and the entry's id alone would give them one.

    A concrete entry names its content and a slot binds late, which is why ``binding`` and
    ``title`` are each required for exactly one kind. A filled slot's block carries the
    binding of the habit or task that filled it, so a slot has no content identity here to
    carry, and no name either: nothing has been chosen for it to name.

    ``title`` is the CONTENT's own name, resolved by the producer from the routine or habit
    row the entry names. It is carried rather than joined out of this struct, because no join
    inside the struct is total: ``habit_occurrences`` is cadence-filtered, so a concrete entry
    naming a habit that is not due this week would find no name at all.

    ``area_id`` is required for BOTH kinds, because a block that is neither the frame nor an
    anchor carries an Area. For a slot it is the declared Area; for a concrete entry it is its
    content's, falling back to the entry's own declaration. An entry whose Area resolves to
    neither cannot become a block, so the producer drops it rather than carrying one nothing
    can place.

    ``day_type_name`` is the DAY SHAPE's own name, resolved by the producer from the ``day_types``
    row the week pattern maps this date to. Carried beside ``title`` for the same reason: the
    clause a block renders is built from resolved inputs alone, and the one fact a reader cannot
    recover from the content's own title is which kind of day placed it.
    """

    entry_id: TemplateEntryId
    occurrence_key: str
    kind: TemplateEntryKind
    interval: Interval
    flex_band_minutes: int
    area_id: AreaId
    day_type_name: str
    title: str | None = None
    binding: EntryBinding | None = None

    def __post_init__(self) -> None:
        _require_content_matching_the_kind(self.kind, self.binding, self.title)

    @property
    def block_binding(self) -> BindingRef:
        """The identity the block this entry materializes into carries.

        Distinct from ``binding``, which names the CONTENT: which of a habit's occurrences a
        concrete entry claims is decided when content is bound, so a block of an entry is keyed by
        the entry and the date instead.
        """
        return BindingRef(BindingKind.TEMPLATE_ENTRY, self.entry_id, self.occurrence_key)


@dataclass(frozen=True, slots=True, kw_only=True)
class HabitOccurrence:
    """One occurrence of one habit, expanded from its cadence.

    ``binding`` is keyed by the occurrence's zero-padded index in expansion order, so
    reducing a cadence drops the highest ordinals and re-keys none of the survivors.

    ``duration`` is fixed, or elastic with a minimum and a maximum the solver sizes
    within. An elastic range arrives already scaled by the active duration multiplier.

    ``is_debt`` marks an occurrence added to make up an earlier miss rather than a fresh
    one. It is a fact about this expansion and it is not written onto an outcome, so a
    later week's debt derivation cannot tell a made-up completion from a fresh one.

    ``binding_source`` is the habit's own, carried because the solver reads it twice: a
    ``queue`` occurrence draws its content from the backlog when it is bound, and every
    occurrence's ``bound`` clause names the source that produced its content. It is NOT
    derivable from ``variant``: a rotation resolves one, and ``fixed`` and ``queue`` both
    resolve none, so those two would be indistinguishable and no occurrence could be
    bound from the backlog at all.
    """

    binding: BindingRef
    duration: Duration
    area_id: AreaId
    title: str
    binding_source: BindingSource
    variant: str | None = None
    is_debt: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class EligibleTask:
    """One open task the solver may place, and how much of it is left to place.

    ``remaining_minutes`` is the estimate, corrected by the active duration multiplier,
    less recorded minutes, less the attributed span of each immovable placement clipped
    at ``now``, where immovable means a past block or a pin: only what the outcome log
    says was actually done of the blocks the solver cannot re-place nets out of the
    figure. A confirmed skip therefore raises it by its minutes, and a pinned block
    ahead of ``now`` nets nothing until it is lived, because the solver discards and
    re-places what has not happened and netting it would permanently under-schedule the
    task.

    **This is the SOLVER's quantity.** It is read by construction and by local search, and
    by nothing else. The probe reads ``DeadlineDemand.remaining_minutes``, which nets a
    different set for the reason the module docstring states.
    """

    binding: BindingRef
    remaining_minutes: int
    priority: Priority
    min_chunk_minutes: int
    splittable: bool
    area_id: AreaId
    title: str
    deadline: Instant | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AreaBudget:
    """One Area's floors, target, and what is already placed in it, for this week.

    The two floor quantities are the pair this struct exists to keep apart. Merging them
    reports a floor shortfall on the normal healthy state of the product, because a
    healthy week is by definition one whose floors are met by solver-placed blocks and
    solver-placed blocks are unpinned.
    """

    area_id: AreaId
    # The Area's own name, carried because a shortfall names what cannot be satisfied in the
    # user's words, and the probe resolves no identifier: it performs no lookup at all.
    name: str
    # NET of IMMOVABLE placements in this Area only, clamped at zero. The SOLVER's
    # quantity, read by nothing else, because the rule it serves is that the solver never
    # leaves an Area under a floor the week could still meet and only an approved breach
    # may go under it: an unpinned block is about to be re-placed, so reserving against
    # it would let the solver under-place the floor by whatever the previous solve
    # happened to place. A PIN lowers this figure by exactly the pinned block's minutes.
    floor_minutes: int
    # The declared floor less the minutes the week's placements give this Area: what an outcome
    # said happened before `now`, plus what each placement occupies from `now` on, clamped at
    # zero. The PROBE's quantity, projected verbatim by
    # `for_probe()`: the probe compares against `free`, and `free` subtracts every
    # placement's future part, so a reservation netting a different set ahead of `now` would count
    # two sets on one comparison. Behind `now` the attribution table decides instead, which is why
    # a confirmed skip of a past hour RAISES this figure. A pin leaves it UNCHANGED.
    # The asymmetry between the two figures above has one reason: a quantity that did not
    # fall would make the solver place five hours on top of the pinned one and over-serve
    # the floor by an hour.
    floor_reservation_minutes: int
    # The DECLARED floor as the Area states it, NET of NO placement set: user intent rather
    # than either reservation above, both of which read it today as their subtrahend. Gross,
    # and so in need of no clamp: nothing is subtracted from it.
    declared_floor_minutes: int
    # The declared floor plus this Area's share of the remainder. GROSS, net of nothing,
    # because it is a reporting figure rather than a reservation.
    target_minutes: int
    # EVERY placement in this Area, pinned or not, past or future, read exactly the way the
    # reservation above reads them: what an outcome said happened before `now`, and what each
    # placement occupies from `now` on. Named here so the `floor` reason clause cannot disagree
    # with whichever reservation a reader compares it against.
    placed_minutes: int
    # Read by H8. From an AREA preference only, so no override can relax a hard cap.
    max_per_day_minutes: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedPreference:
    """When one owner's work should happen, resolved down the override chain.

    ``owner`` is an Area, a Habit, or a Task, already resolved: an override replaces its
    Area's declaration wholly, so what arrives here is one preference rather than two to
    merge. A habit that declares none carries its Area's, under its own owner, so the
    solver walks no chain.

    ``windows`` are instants for THIS week: each declared wall-time window resolved against the
    dates of the week, in the zone active on each date. **This can hold fewer than one interval per
    date per declaration**, and an interval can be narrower or wider than the declaration: a date
    whose own daylight-saving gap leaves the window's resolved bounds not running forward
    contributes nothing, and a date holding a gap or a repeat inside the window contributes a
    shorter or longer one. So a reader counts what is here rather than sizing on seven times the
    declaration count, and the producer states the arithmetic of both directions.

    **These are merged where they meet, and one of them can span two dates.** A window ending at the
    day's end closes on the following date, so a stretch the user authored across midnight arrives
    as one interval covering the night rather than as the two halves it is stored as, and two
    windows declared to abut likewise arrive as one. So the count is not the declaration count
    either way, and an interval's own two ends can name different dates.

    There is no ``max_per_day`` here, and its absence is the rule: a daily cap is an
    Area's and travels on ``AreaBudget``.
    """

    owner: PreferenceOwner
    windows: tuple[Interval, ...]
    strength: PreferenceStrength
    preferred_duration_minutes: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Anchor:
    """One imported commitment, as hard occupancy. Immovable external fact.

    The title is the one the week was assembled against, so a retitled anchor does not
    change what an approved week says.
    """

    anchor_id: AnchorId
    interval: Interval
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ShadowBlock:
    """A prep or transit block an anchor cast, with the Area its type named.

    A block rather than a window, because it carries an Area: it is discretionary time
    ALLOCATED to that Area in the same way a task is. A buffer whose type named no Area is
    a forbidden window instead and travels in ``forbidden_windows``. The type and commitment
    names are resolved before clipping, so a clause remains complete when its commitment falls
    outside this week's span.
    """

    binding: BindingRef
    interval: Interval
    area_id: AreaId
    title: str
    anchor_type_name: str
    anchor_title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Pin:
    """Where the user put a block, and what the solver had chosen instead.

    Immovable to the solver, and distinct from a block fixed by derivation in everything
    else: a pin is the user's own edit, so it renders a pin glyph and it is a training
    label.

    ``superseded_placement`` and ``objective_delta`` travel together and are what the
    reason panel renders, so it never has to walk the edit log.
    """

    binding: BindingRef
    interval: Interval
    pinned_on: Date
    superseded_placement: Interval | None = None
    objective_delta: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WeekAdjustment:
    """One approved concession, already folded into the fields it modifies.

    Carried so a reason clause can cite the concession a week was solved under, which is
    what stops a week looking feasible for a cause the user cannot see. Folding it a
    second time from here would double it.

    ``reductions`` carries per-date minutes for a routine reduction and is empty for the
    other three kinds. The enumerator chose the distribution, so the concession stores the
    result rather than a rule for re-deriving it against inputs that have since changed.

    ``delta_minutes`` is an INCREMENT: how much this concession lowers the figure it names,
    against that figure as it stands, rather than an absolute target it should end at. Set
    for ``breach_floor`` and null for the other three. Three components read the column and
    the reading has to be one: the enumerator computes it over an already-folded assembly,
    so a second concession on one target lowers what the first left.
    """

    adjustment_id: WeekAdjustmentId
    kind: AdjustmentKind
    target_id: UUID
    reductions: Mapping[Date, int] = field(default_factory=dict)
    delta_minutes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reductions", dict(self.reductions))


@dataclass(frozen=True, slots=True, kw_only=True)
class SolveInputs:
    """One week's inputs, fully resolved. The solver performs no lookups over this.

    The rotation cursor is already derived, debt is already applied, the frame's local
    times are already instants at their effective durations, approved concessions are
    already folded in, and Area figures are already minutes for this specific week.
    """

    iso_week: IsoWeek
    # The week's TRUE elapsed span, bounded by the zone active on each of its two Mondays,
    # so a transition week is 167 or 169 hours and a travel week resolves two zones.
    span: Interval
    # The instant this assembly was built against, stamped by the assembler from its own
    # argument and never read from a clock. H10 cannot decide "has started or is in the
    # past" without it, and the probe clips its capacity to it.
    now: Instant
    zone_by_date: Mapping[Date, ZoneId]
    input_version: int

    frame: tuple[FrameEntry, ...] = ()
    # The PRECEDING week's frame occurrences, as the spans they occupy in THIS one, clipped to
    # the span. A Sunday `Sleep 23:00 + 8h` belongs to the week its start falls in and runs into
    # the next one, where the time is genuinely occupied.
    #
    # Spans rather than entries, because one week owns the occurrence: it holds the whole
    # interval at the routine's own duration and materializes the one block. There is nothing
    # here a second document could hold, so the occurrence cannot appear twice.
    #
    # Read through `frame_occupancy()` together with `frame` above. Both consumers ask the same
    # question of both fields, and a consumer reading `frame` alone would place work inside a
    # night the preceding week already spent.
    frame_overhang: tuple[Interval, ...] = ()
    # Hard occupancy: an immovable external fact. Every anchor OVERLAPPING the span, at its own
    # real time and unclipped, because a commitment's duration is the source's fact rather than
    # this week's reading of it. Every figure taken over these subtracts within the span.
    anchors: tuple[Anchor, ...] = ()
    # Prep and transit blocks, with the Area their type named, clipped to the span. SOLVER only:
    # the probe sees them through `placed`, never as a separate subtrahend, because a shadow
    # block is discretionary time ALLOCATED to an Area in the same way a task is.
    shadow_blocks: tuple[ShadowBlock, ...] = ()
    # Recovery windows and unattributed buffers, each with its scope intact. The split by
    # scope happens in `for_probe()` and NOWHERE else, which is what stops the solver's
    # and the probe's readings of one window drifting apart again.
    forbidden_windows: tuple[ForbiddenWindow, ...] = ()
    # Journeys a collision dropped whole inside the span, already shaped as the empty slots that
    # explain them. The cause is the assembler's to state, because only it resolved the collision;
    # materialize carries them into the document verbatim and decides nothing about them.
    dropped_legs: tuple[EmptySlot, ...] = ()
    off_plan: tuple[OffPlanPeriod, ...] = ()

    template_entries: tuple[MaterializedEntry, ...] = ()
    habit_occurrences: tuple[HabitOccurrence, ...] = ()
    eligible_tasks: tuple[EligibleTask, ...] = ()
    areas: tuple[AreaBudget, ...] = ()
    preferences: tuple[ResolvedPreference, ...] = ()

    pins: tuple[Pin, ...] = ()
    deadline_demands: tuple[DeadlineDemand, ...] = ()
    adjustments: tuple[WeekAdjustment, ...] = ()
    live_plan: PlanDocument | None = None
    churn_baseline: ChurnBaseline = field(default_factory=ChurnBaseline.never_approved)

    def __post_init__(self) -> None:
        object.__setattr__(self, "now", as_instant(self.now))
        object.__setattr__(self, "zone_by_date", dict(self.zone_by_date))
        require_a_zone_for_every_day(self.iso_week, self.zone_by_date)
        _require_the_overhang_inside_the_span(self.span, self.frame_overhang)

    def frame_occupancy(self) -> IntervalSet:
        """Every span the circadian frame occupies in this week, this week's and inherited.

        One question with one answer, asked by H3 and by the probe's ``occupied``. Behind one
        call rather than two fields each consumer unions itself, because the preceding week's
        overhang is occupancy for exactly the same reason this week's own occurrences are.
        """
        return frame_occupancy(self.frame, self.frame_overhang)

    def committed_occupancy(self) -> IntervalSet:
        """Every span this week has already committed to something: the plan's blocks and the pins.

        **A pin and the live-plan block it pins are one placement.** They are paired by binding
        and the pin's interval wins, because that is where the block is. Unioned unpaired, a
        dragged block would occupy both where it was and where the user put it, and free capacity
        would lose an hour the week still has.

        The api's netting states the same pairing over per-placement attribution, because it needs
        each placement's Area and whether the solver may still move it. The two are crossed
        against each other in the api suite rather than one being written in terms of the other:
        this is a union of intervals and that is an index by task and by Area.
        """
        pinned = {pin.binding for pin in self.pins}
        blocks = () if self.live_plan is None else self.live_plan.blocks
        return IntervalSet(
            [
                *(block.interval for block in blocks if block.binding not in pinned),
                *(pin.interval for pin in self.pins),
            ]
        )

    def for_probe(self) -> ProbeInputs:
        """The capacity arithmetic's reading of this week. A projection, not a second assembly.

        It splits the forbidden windows by scope, flattens the typed collections into interval
        sets, and carries the netted demands and reservations forward **verbatim**. It computes no
        netting: the assembler did that, and re-deriving it here is the one mistake this
        projection must not make. No lookup and no clock read either, so two projections of one
        assembly are equal.

        The verdict's own instant is the instant this assembly was stamped with. A verdict is a
        fact about one assembly, so reading a clock here would make it irreproducible from stored
        inputs for the sake of the microseconds between the two.

        **``shadow_blocks`` is deliberately absent.** A prep or transit block carries an Area, so
        it is discretionary time allocated to that Area rather than removed from the week, and the
        probe sees it through ``placed`` once a plan holds it. Subtracting one would count it
        twice over a whole week: out of every figure's denominator and against the Area's own
        minutes at once. Before a week is first solved it holds none, so the probe counts that
        time as free: capacity arithmetic then over-credits rather than over-reports, which is
        the only direction a check that may not prove feasibility can safely err in.
        """
        return ProbeInputs(
            span=self.span,
            now=self.now,
            computed_at=self.now,
            input_version=self.input_version,
            frame=self.frame_occupancy(),
            anchors=IntervalSet(anchor.interval for anchor in self.anchors),
            absolute_forbidden=IntervalSet(
                window.interval
                for window in self.forbidden_windows
                if window.scope is ForbiddenScope.ALL
            ),
            scoped_forbidden=tuple(
                ScopedWindow(interval=window.interval, forbidden_area_ids=window.forbidden_area_ids)
                for window in self.forbidden_windows
                if window.scope is ForbiddenScope.AREAS
            ),
            off_plan=IntervalSet(period.interval for period in self.off_plan),
            placed=self.committed_occupancy(),
            area_floor_reservations=tuple(
                FloorReservation(
                    area_id=area.area_id,
                    reserved_minutes=area.floor_reservation_minutes,
                    label=area.name,
                )
                for area in self.areas
            ),
            area_targets={area.area_id: area.target_minutes for area in self.areas},
            deadline_demands=self.deadline_demands,
        )

    @property
    def seed(self) -> int:
        """The seed any tie a comparator cannot break is resolved with. Derived, never set.

        Determinism, not randomness: it is a function of the week and the input version, so
        two assemblies of unchanged inputs produce the same seed and a solve is reproducible
        from stored data. There is no field for it, for the same reason a block's id has
        none: a value that can be supplied can be supplied wrongly.

        The week is in the digest as well as the version, so two weeks sitting at the same
        input version do not share a seed.
        """
        digest = sha256(f"{self.iso_week}\x1f{self.input_version}".encode()).digest()
        return int.from_bytes(digest[:_SEED_BYTES])


def _require_content_matching_the_kind(
    kind: TemplateEntryKind, binding: EntryBinding | None, title: str | None
) -> None:
    """A concrete entry names content and a slot names none, in both directions.

    Both halves protect the block an entry becomes. A concrete entry missing either half
    cannot be placed at all: a block carries the resolved content name, and an empty name
    names nothing. A slot carrying either would be a concrete entry claiming to bind late,
    and the name would be a choice nobody has made.
    """
    named = kind is TemplateEntryKind.CONCRETE
    for what, present in (("a binding", binding is not None), ("a title", bool(title))):
        if present == named:
            continue
        states = "names its content" if named else "leaves its content to be bound"
        holds = "carries no" if named else "carries"
        raise PlanError(
            f"a {kind.value!r} entry {states}, and this one {holds} {what}: the block an entry "
            "becomes carries the resolved content name, so a name and the content it names "
            "arrive together or neither does"
        )


def frame_occupancy(frame: Sequence[FrameEntry], overhang: Sequence[Interval]) -> IntervalSet:
    """The spans a week's circadian frame occupies, its own occurrences and the inherited ones.

    Stated here rather than at each call site, because the producer needs it before the struct
    exists: the discretionary denominator subtracts the frame, and it is computed while the
    fields are still being resolved.
    """
    return IntervalSet([*(entry.interval for entry in frame), *overhang])


def _require_the_overhang_inside_the_span(span: Interval, overhang: Sequence[Interval]) -> None:
    """The inherited spans describe THIS week, so none of them may name time outside it.

    A member reaching past the span would be the preceding week's occurrence carried whole
    rather than clipped, which would subtract minutes this week does not hold from a figure
    taken over it. Refused rather than clipped here: which week owns an occurrence is the
    producer's question, and silently correcting it would hide a producer that answered wrongly.
    """
    outside = [member for member in overhang if member.start < span.start or member.end > span.end]
    if outside:
        raise PlanError(
            f"{len(outside)} of {len(overhang)} inherited frame spans reach outside "
            f"[{span.start}, {span.end}): an overhang is the part of the preceding week's "
            "occurrence that falls in this week, so it is clipped to this week's span"
        )
