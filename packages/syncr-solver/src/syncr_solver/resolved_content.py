"""Resolved content and immovable facts carried by ``SolveInputs``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syncr_domain.habits import BindingSource as BindingSource  # noqa: TC001
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.plan import PlanError
from syncr_domain.templates import TemplateEntryKind

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from syncr_domain.habits import Duration
    from syncr_domain.identifiers import (
        AnchorId,
        AreaId,
        RoutineId,
        TemplateEntryId,
        WeekAdjustmentId,
    )
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import AdjustmentKind
    from syncr_domain.preferences import PreferenceOwner, PreferenceStrength
    from syncr_domain.templates import BindingTarget
    from syncr_domain.zones import Date


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
