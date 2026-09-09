"""A stored failure snapshot, read back into the inputs the solve that failed was given.

``snapshots.py`` writes the document and this reads it, and neither direction proves anything
alone. A write with no read cannot be shown to be faithful: a value the walk drops writes
successfully forever, and the local reproduction the snapshot exists for would then run against
a week that is not the one that failed.

**The document's keys are the value's own field names**, because the encoder walks the dataclass
rather than naming a key per field. So this reader names each key exactly once, and the path a
refusal reports is derived from the key rather than spelled beside it.

**A field the value has and this module holds no form for is refused, not defaulted.** That is the
mirror of the encoder's refusal to write a leaf it has no form for, and it is the whole reason the
inventory is taken from ``dataclasses.fields`` here: inputs rebuilt with a field at its default are
not the inputs that failed, and nothing about the rebuilt value would say so.

**Every member is rebuilt through its own constructor, and a broken invariant is refused where it
is read**, in the same words and the same exception a stored plan document uses. Uniformly, rather
than only for the member types that validate something today: which types those are is not a
question a reader of this module should have to answer, and a type that gains an invariant later
would otherwise raise past this boundary as a domain error nothing here names a field for.

**Four shapes cover every field.** A leaf, a collection of one shape, a map keyed by local date,
and a value that may be absent. Each has one combinator here, and every reader in this module has
the signature the leaf codecs have, so the shapes compose with no adapter between them.
"""

from __future__ import annotations

import dataclasses
from functools import partial
from typing import TYPE_CHECKING, Any, Final

from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_api.plans.stored_documents import plan_document, read_binding
from syncr_api.plans.stored_values import (
    read_date,
    read_flag,
    read_id,
    read_instant,
    read_interval,
    read_list,
    read_mapping,
    read_member,
    read_optional_id,
    read_optional_instant,
    read_optional_interval,
    read_optional_number,
    read_optional_text,
    read_optional_whole_number,
    read_text,
    read_whole_number,
    rebuilt,
)
from syncr_api.solving.snapshots import FORM, INPUTS, SNAPSHOT_FORM
from syncr_domain.feasibility import DeadlineDemand
from syncr_domain.gaps import (
    EmptySlot,
    EmptySlotReason,
    ForbiddenKind,
    ForbiddenScope,
    ForbiddenWindow,
)
from syncr_domain.habits import BindingSource, Duration
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.plan import AdjustmentKind
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind, PreferenceStrength
from syncr_domain.tasks import Priority
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import (
    Anchor,
    AreaBudget,
    ChurnBaseline,
    EligibleTask,
    EntryBinding,
    FrameEntry,
    FrameOverhang,
    HabitOccurrence,
    MaterializedEntry,
    Pin,
    ResolvedPreference,
    ShadowBlock,
    SolveInputs,
    WeekAdjustment,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from typing import Protocol
    from uuid import UUID

    from syncr_api.core.columns import JsonDocument
    from syncr_domain.plan import PlanDocument
    from syncr_domain.zones import Date

    class _Read(Protocol):
        """One stored value, read under the field a refusal has to name."""

        def __call__(self, value: object, *, field: str) -> Any: ...

    class _ReadHeld(Protocol):
        """One field of a stored member, read under the path its own refusal names."""

        def __call__(self, key: str, read: _Read) -> Any: ...


class UnreadableSnapshot(Exception):
    """A field of the inputs this module holds no stored form for, so a read would default it."""


# What a refusal calls the whole document, which no key names because it is the column itself.
SNAPSHOT = "the snapshot"


def inputs_of(snapshot: JsonDocument) -> SolveInputs:
    """The inputs the solve that wrote ``snapshot`` read, or a stated refusal.

    The document is read as an object before anything is read out of it, so the envelope refuses
    the way every level below it does. The annotation is not what makes that safe: the column is
    nullable ``JSONB`` and no constraint on it says the value is an object, so what arrives is
    whatever was stored, and a reader that indexed it first would answer a corrupt row with an
    ``AttributeError`` naming a Python type instead of a refusal naming the document.
    """
    stored_snapshot = read_mapping(snapshot, field=SNAPSHOT)
    form = read_whole_number(stored_snapshot.get(FORM), field=FORM)
    if form != SNAPSHOT_FORM:
        raise StoredDocumentCorrupt(
            f"{FORM} names {form} and this reader rebuilds {SNAPSHOT_FORM}: the figure is bumped "
            "when the walk changes shape, so reading one shape as the other would rebuild inputs "
            "no solve ever held"
        )
    require_a_reader_for_every_field([named for named, _ in FORMS])
    stored = read_mapping(stored_snapshot.get(INPUTS), field=INPUTS)
    return rebuilt(
        lambda: SolveInputs(
            **{named: read(stored.get(named), field=named) for named, read in FORMS}
        ),
        field=INPUTS,
    )


def require_a_reader_for_every_field(named: Collection[str]) -> None:
    """Raise unless the stored forms named cover exactly the fields the inputs have.

    Stated over the names rather than over the table itself, so the refusal can be driven from a
    set this module does not hold: a guard whose only input is the shipped table passes for as
    long as the table is right and says nothing about what happens when it is not.
    """
    held = {field.name for field in dataclasses.fields(SolveInputs)}
    unread = sorted(held - set(named))
    unclaimed = sorted(set(named) - held)
    if not unread and not unclaimed:
        return
    raise UnreadableSnapshot(
        f"the inputs hold {len(held)} fields and this module states {len(named)} stored forms: "
        f"{unread} have no form and {unclaimed} name no field. A field read as its default is not "
        "what the solve failed on, and the rebuilt value would not say which field it lost"
    )


def _fields_of(value: object, *, field: str) -> _ReadHeld:
    """One stored member's own fields, each read under the path a refusal has to name.

    The path is derived from the key here rather than written beside each read, because a member
    naming its key twice is a member whose refusal can name a field it did not read.
    """
    stored = read_mapping(value, field=field)

    def read_field(key: str, read: _Read) -> Any:
        return read(stored.get(key), field=f"{field}.{key}")

    return read_field


def _every(read: _Read) -> _Read:
    """One collection, each member read under a field naming its position.

    The position is in the field name for the reason a stored document states: a refusal has to
    say WHICH member of a week could not be rebuilt, and a week holds hundreds that are not named.
    """

    def read_all(value: object, *, field: str) -> tuple[Any, ...]:
        return tuple(
            _one(read, member, field=f"{field}[{position}]")
            for position, member in enumerate(read_list(value, field=field))
        )

    return read_all


def _one(read: _Read, value: object, *, field: str) -> Any:
    """One member of a collection, with a domain refusal from any depth naming that member."""
    return rebuilt(lambda: read(value, field=field), field=field)


def _by_date(read: _Read) -> _Read:
    """One map keyed by local date, whose keys are parsed rather than taken as text."""

    def read_map(value: object, *, field: str) -> dict[Date, Any]:
        stored = read_mapping(value, field=field)
        return {
            read_date(day, field=f"{field}[{day!r}]"): read(held, field=f"{field}[{day!r}]")
            for day, held in stored.items()
        }

    return read_map


def _optional(read: _Read) -> _Read:
    """One value the document may state nothing for."""

    def read_maybe(value: object, *, field: str) -> Any:
        return None if value is None else read(value, field=field)

    return read_maybe


def _read_week(value: object, *, field: str) -> IsoWeek:
    return rebuilt(lambda: IsoWeek.parse(read_text(value, field=field)), field=field)


def _read_frame_entry(value: object, *, field: str) -> FrameEntry:
    held = _fields_of(value, field=field)
    return FrameEntry(
        routine_id=held("routine_id", read_id),
        occurrence_key=held("occurrence_key", read_text),
        interval=held("interval", read_interval),
        min_duration_minutes=held("min_duration_minutes", read_whole_number),
        flex_band_minutes=held("flex_band_minutes", read_whole_number),
        title=held("title", read_text),
    )


def _read_frame_overhang(value: object, *, field: str) -> FrameOverhang:
    held = _fields_of(value, field=field)
    return FrameOverhang(
        interval=held("interval", read_interval),
        label=held("label", read_text),
    )


def _read_anchor(value: object, *, field: str) -> Anchor:
    held = _fields_of(value, field=field)
    return Anchor(
        anchor_id=held("anchor_id", read_id),
        interval=held("interval", read_interval),
        title=held("title", read_text),
    )


def _read_shadow_block(value: object, *, field: str) -> ShadowBlock:
    held = _fields_of(value, field=field)
    return ShadowBlock(
        binding=held("binding", read_binding),
        interval=held("interval", read_interval),
        area_id=held("area_id", read_id),
        title=held("title", read_text),
        anchor_type_name=held("anchor_type_name", read_text),
        anchor_title=held("anchor_title", read_text),
    )


def _read_dropped_leg(value: object, *, field: str) -> EmptySlot:
    held = _fields_of(value, field=field)
    return EmptySlot(
        interval=held("interval", read_interval),
        area_id=held("area_id", read_id),
        reason=held("reason", partial(read_member, EmptySlotReason)),
    )


def _read_forbidden_window(value: object, *, field: str) -> ForbiddenWindow:
    held = _fields_of(value, field=field)
    return ForbiddenWindow(
        interval=held("interval", read_interval),
        kind=held("kind", partial(read_member, ForbiddenKind)),
        scope=held("scope", partial(read_member, ForbiddenScope)),
        forbidden_area_ids=held("forbidden_area_ids", _every(read_id)),
        label=held("label", read_text),
        anchor_id=held("anchor_id", read_id),
    )


def _read_off_plan_period(value: object, *, field: str) -> OffPlanPeriod:
    held = _fields_of(value, field=field)
    return OffPlanPeriod(
        interval=held("interval", read_interval),
        keep_frame=held("keep_frame", read_flag),
        label=held("label", read_optional_text),
    )


def _read_template_entry(value: object, *, field: str) -> MaterializedEntry:
    held = _fields_of(value, field=field)
    return MaterializedEntry(
        entry_id=held("entry_id", read_id),
        occurrence_key=held("occurrence_key", read_text),
        kind=held("kind", partial(read_member, TemplateEntryKind)),
        interval=held("interval", read_interval),
        flex_band_minutes=held("flex_band_minutes", read_whole_number),
        area_id=held("area_id", read_id),
        day_type_name=held("day_type_name", read_text),
        title=held("title", read_optional_text),
        binding=held("binding", _optional(_read_entry_binding)),
    )


def _read_entry_binding(value: object, *, field: str) -> EntryBinding:
    held = _fields_of(value, field=field)
    return EntryBinding(
        target=held("target", partial(read_member, BindingTarget)),
        entity_id=held("entity_id", read_id),
    )


def _read_habit_occurrence(value: object, *, field: str) -> HabitOccurrence:
    held = _fields_of(value, field=field)
    return HabitOccurrence(
        binding=held("binding", read_binding),
        duration=held("duration", _read_duration),
        area_id=held("area_id", read_id),
        title=held("title", read_text),
        binding_source=held("binding_source", partial(read_member, BindingSource)),
        variant=held("variant", read_optional_text),
        is_debt=held("is_debt", read_flag),
    )


def _read_duration(value: object, *, field: str) -> Duration:
    held = _fields_of(value, field=field)
    return Duration(
        min_minutes=held("min_minutes", read_whole_number),
        max_minutes=held("max_minutes", read_whole_number),
    )


def _read_eligible_task(value: object, *, field: str) -> EligibleTask:
    held = _fields_of(value, field=field)
    return EligibleTask(
        binding=held("binding", read_binding),
        remaining_minutes=held("remaining_minutes", read_whole_number),
        priority=held("priority", partial(read_member, Priority)),
        min_chunk_minutes=held("min_chunk_minutes", read_whole_number),
        splittable=held("splittable", read_flag),
        area_id=held("area_id", read_id),
        title=held("title", read_text),
        deadline=held("deadline", read_optional_instant),
    )


def _read_area_budget(value: object, *, field: str) -> AreaBudget:
    held = _fields_of(value, field=field)
    return AreaBudget(
        area_id=held("area_id", read_id),
        name=held("name", read_text),
        floor_minutes=held("floor_minutes", read_whole_number),
        floor_reservation_minutes=held("floor_reservation_minutes", read_whole_number),
        declared_floor_minutes=held("declared_floor_minutes", read_whole_number),
        target_minutes=held("target_minutes", read_whole_number),
        placed_minutes=held("placed_minutes", read_whole_number),
        max_per_day_minutes=held("max_per_day_minutes", read_optional_whole_number),
    )


def _read_preference(value: object, *, field: str) -> ResolvedPreference:
    held = _fields_of(value, field=field)
    return ResolvedPreference(
        owner=held("owner", _read_preference_owner),
        windows=held("windows", _every(read_interval)),
        strength=held("strength", partial(read_member, PreferenceStrength)),
        preferred_duration_minutes=held("preferred_duration_minutes", read_optional_whole_number),
    )


def _read_preference_owner(value: object, *, field: str) -> PreferenceOwner:
    held = _fields_of(value, field=field)
    return PreferenceOwner(
        kind=held("kind", partial(read_member, PreferenceOwnerKind)),
        id=held("id", read_id),
    )


def _read_pin(value: object, *, field: str) -> Pin:
    held = _fields_of(value, field=field)
    return Pin(
        binding=held("binding", read_binding),
        interval=held("interval", read_interval),
        pinned_on=held("pinned_on", read_date),
        superseded_placement=held("superseded_placement", read_optional_interval),
        objective_delta=held("objective_delta", read_optional_number),
    )


def _read_deadline_demand(value: object, *, field: str) -> DeadlineDemand:
    held = _fields_of(value, field=field)
    return DeadlineDemand(
        deadline=held("deadline", read_instant),
        remaining_minutes=held("remaining_minutes", read_whole_number),
        area_id=held("area_id", read_id),
        labels=held("labels", _every(read_text)),
        contributors=held("contributors", _every(_read_contributor)),
    )


def _read_contributor(value: object, *, field: str) -> tuple[UUID, int]:
    """One per-task pair, as the two-member array the walk stores a tuple as."""
    held = read_list(value, field=field)
    if len(held) != 2:
        raise StoredDocumentCorrupt(
            f"{field} holds {len(held)} members, and a per-task pair states two: the task and "
            "the minutes it owes"
        )
    return (
        read_id(held[0], field=f"{field}[0]"),
        read_whole_number(held[1], field=f"{field}[1]"),
    )


def _read_adjustment(value: object, *, field: str) -> WeekAdjustment:
    held = _fields_of(value, field=field)
    return WeekAdjustment(
        adjustment_id=held("adjustment_id", read_id),
        kind=held("kind", partial(read_member, AdjustmentKind)),
        target_id=held("target_id", read_id),
        reductions=held("reductions", _by_date(read_whole_number)),
        delta_minutes=held("delta_minutes", read_optional_whole_number),
    )


def _read_plan(value: object, *, field: str) -> PlanDocument:
    """One stored plan, read by the document codec, under the field this snapshot holds it at.

    The refusal is re-raised carrying that field because a snapshot holds TWO plans: the live one
    and the one churn is measured against. The document codec names the part of a week it could not
    rebuild and cannot name which week it was reading, so a refusal passed through unchanged would
    leave an operator with two documents and no way to tell which of them is the corrupt one.
    """
    stored = read_mapping(value, field=field)
    try:
        return plan_document(stored)
    except StoredDocumentCorrupt as refused:
        raise StoredDocumentCorrupt(f"{field}: {refused}") from refused


def _read_churn_baseline(value: object, *, field: str) -> ChurnBaseline:
    """The plan churn is measured against, or the baseline of a week that has approved none.

    An absent key reads as never-approved rather than as a refusal, for the reason an absent
    collection reads as empty: a document written before a field existed states no key for it, and
    the value's own default is what such a document meant.
    """
    if value is None:
        return ChurnBaseline.never_approved()
    held = _fields_of(value, field=field)
    return rebuilt(
        lambda: ChurnBaseline(
            revision_id=held("revision_id", read_optional_id),
            approved_at=held("approved_at", read_optional_instant),
            document=held("document", _optional(_read_plan)),
        ),
        field=field,
    )


# One stored form per field of the inputs, and the only statement of what this module reads. The
# constructor call is built from it, so the coverage the guard above asserts is the coverage the
# read has rather than a list beside it that could agree with neither. The order is the order the
# value declares its fields in.
#
# Pairs rather than a mapping display, and that is not a style choice: four of these field names are
# also keys a stored plan document holds, and `tests/test_stored_plan_document.py` reports any
# mapping naming the week key plus one more of them as a second producer of a document. This module
# produces none -- it reads one, through that document's own reader -- so it states its table in a
# shape that claim cannot be made about.
#
# Public for the reason the clause readers are: a form per field is a claim about this value's
# shape, and the test that crosses it against the value's own fields has to be able to read it.
FORMS: Final[tuple[tuple[str, _Read], ...]] = (
    ("iso_week", _read_week),
    ("span", read_interval),
    ("now", read_instant),
    ("zone_by_date", _by_date(read_text)),
    ("input_version", read_whole_number),
    ("frame", _every(_read_frame_entry)),
    ("frame_overhang", _every(_read_frame_overhang)),
    ("anchors", _every(_read_anchor)),
    ("shadow_blocks", _every(_read_shadow_block)),
    ("forbidden_windows", _every(_read_forbidden_window)),
    ("dropped_legs", _every(_read_dropped_leg)),
    ("off_plan", _every(_read_off_plan_period)),
    ("template_entries", _every(_read_template_entry)),
    ("habit_occurrences", _every(_read_habit_occurrence)),
    ("eligible_tasks", _every(_read_eligible_task)),
    ("areas", _every(_read_area_budget)),
    ("preferences", _every(_read_preference)),
    ("pins", _every(_read_pin)),
    ("deadline_demands", _every(_read_deadline_demand)),
    ("adjustments", _every(_read_adjustment)),
    ("live_plan", _optional(_read_plan)),
    ("churn_baseline", _read_churn_baseline),
)
