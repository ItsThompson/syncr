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

nets                 IMMOVABLE placements        EVERY placement, pinned or not,
                     only: past blocks and       past or future
                     pins

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

from syncr_domain.intervals import as_instant
from syncr_domain.plan import require_a_zone_for_every_day

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from syncr_domain.gaps import ForbiddenWindow
    from syncr_domain.habits import Duration
    from syncr_domain.identifiers import (
        AnchorId,
        AreaId,
        PlanRevisionId,
        RoutineId,
        TemplateEntryId,
        WeekAdjustmentId,
    )
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.off_plan import OffPlanPeriod
    from syncr_domain.plan import AdjustmentKind, PlanDocument
    from syncr_domain.preferences import PreferenceOwner, PreferenceStrength
    from syncr_domain.tasks import Priority
    from syncr_domain.templates import BindingTarget, TemplateEntryKind
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

    A concrete entry names its content and a slot names an Area and binds late, which is
    why ``binding`` and ``area_id`` are each required for exactly one kind. A filled
    slot's block carries the binding of the habit or task that filled it, so a slot has
    no content identity here to carry.
    """

    entry_id: TemplateEntryId
    occurrence_key: str
    kind: TemplateEntryKind
    interval: Interval
    flex_band_minutes: int
    area_id: AreaId | None = None
    binding: EntryBinding | None = None


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
    """

    binding: BindingRef
    duration: Duration
    area_id: AreaId
    title: str
    variant: str | None = None
    is_debt: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class EligibleTask:
    """One open task the solver may place, and how much of it is left to place.

    ``remaining_minutes`` is the estimate, corrected by the active duration multiplier,
    less recorded minutes, less IMMOVABLE placements only, where immovable means a past
    block or a pin. It does NOT net an unpinned future block, because the solver discards
    and re-places those and netting them would permanently under-schedule the task.

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
class DeadlineDemand:
    """How much work one Area owes before one deadline.

    ``remaining_minutes`` is net, deadline-scoped, and ``max()``-corrected: per task it is
    the corrected estimate less ``max(recorded, minutes placed in the past before the
    deadline)`` less minutes placed in the future before the deadline, and EVERY placement
    counts, pinned or not.

    **This is the PROBE's quantity.** It is read by ``for_probe()`` and by nothing else.
    The solver reads ``EligibleTask.remaining_minutes``.

    ``labels`` names the tasks that contribute, for the shortfall message. Several tasks
    sharing one deadline in one Area are one demand, because the probe compares a demand
    against the capacity that Area has before that instant.
    """

    deadline: Instant
    remaining_minutes: int
    area_id: AreaId
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class AreaBudget:
    """One Area's floors, target, and what is already placed in it, for this week.

    The two floor quantities are the pair this struct exists to keep apart. Merging them
    reports a floor shortfall on the normal healthy state of the product, because a
    healthy week is by definition one whose floors are met by solver-placed blocks and
    solver-placed blocks are unpinned.
    """

    area_id: AreaId
    # NET of IMMOVABLE placements in this Area only, clamped at zero. The SOLVER's
    # quantity, read by H9 and by nothing else: an unpinned block is about to be
    # re-placed, so reserving against it would let the solver under-place the floor by
    # whatever the previous solve happened to place.
    floor_minutes: int
    # The declared floor less minutes placed in this Area by ANY block, pinned or not,
    # past or future, clamped at zero. The PROBE's quantity, projected verbatim by
    # `for_probe()`: the probe compares against `free`, and `free` subtracts every
    # placement, so a reservation netting only immovable placements would count a
    # different set on each side of one comparison.
    floor_reservation_minutes: int
    # The declared floor plus this Area's share of the remainder. GROSS, net of nothing,
    # because it is a reporting figure rather than a reservation.
    target_minutes: int
    # EVERY placement in this Area, pinned or not, past or future, which is the same set
    # the reservation above nets. Named here so the `floor` reason clause cannot disagree
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
    a forbidden window instead and travels in ``forbidden_windows``.
    """

    binding: BindingRef
    interval: Interval
    area_id: AreaId
    title: str


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
    """

    adjustment_id: WeekAdjustmentId
    kind: AdjustmentKind
    target_id: UUID
    reductions: Mapping[Date, int] = field(default_factory=dict)
    delta_minutes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reductions", dict(self.reductions))


@dataclass(frozen=True, slots=True, kw_only=True)
class ChurnBaseline:
    """The revision churn is measured against, or a statement that there is none.

    "The last plan the user saw" is not a persistable definition, so churn is measured
    against the last plan the user APPROVED. A week that has never been approved has zero
    churn and says so, rather than silently comparing against a proposal nobody approved.
    """

    reason: str
    revision_id: PlanRevisionId | None = None
    approved_at: Instant | None = None

    APPROVED_REVISION = "approved-revision"
    NEVER_APPROVED = "never-approved"

    @classmethod
    def never_approved(cls) -> ChurnBaseline:
        """The baseline of a week no revision of which the user has assented to."""
        return cls(reason=cls.NEVER_APPROVED)

    @classmethod
    def approved(cls, revision_id: PlanRevisionId, approved_at: Instant) -> ChurnBaseline:
        """The baseline naming the revision the user approved, and when."""
        return cls(
            reason=cls.APPROVED_REVISION,
            revision_id=revision_id,
            approved_at=as_instant(approved_at),
        )


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
    anchors: tuple[Anchor, ...] = ()
    shadow_blocks: tuple[ShadowBlock, ...] = ()
    # Recovery windows and unattributed buffers, each with its scope intact. The split by
    # scope happens in `for_probe()` and NOWHERE else, which is what stops the solver's
    # and the probe's readings of one window drifting apart again.
    forbidden_windows: tuple[ForbiddenWindow, ...] = ()
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
