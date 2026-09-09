"""The boundary between a failed solve's inputs and the document its operation retains.

``Operation.failed_input_snapshot`` exists so a production failure reproduces locally, and until
now the document had a writer and no reader: nothing in the tree turned one back into inputs, so
nothing could show that what the walk stores is what the solve was given. A field the walk dropped
would have written successfully forever.

Six groups.

**A round trip is an equality.** Written and read back, one week is the same value, over inputs
holding a member of every collection and a stated value for every optional. Asserted per field as
well as whole, so a field that comes back defaulted names itself.

**The equality is only worth what the week is.** Three controls stand under it, each derived from
``dataclasses.fields`` rather than from a list here: every collection holds a member, no field sits
at the value it would default to, and every key the writer states changes what the reader rebuilds.
The third is the one that bites a reader ignoring a key at any depth, which is the failure an
equality over a whole object cannot see.

**The other direction, which is the stronger one.** A stored document read and written again is the
same document. That catches a writer omitting a key the reader defaults and a reader ignoring a key
the writer emits, neither of which a comparison of values can report.

**A field the value has and this module holds no form for.** The inventory is crossed against the
dataclass in both directions, and the refusal is driven from a set the module does not hold.

**A stored form that breaks a member's invariant says so where it is read**, in the same exception
a stored plan document raises and naming the field, driven once per member type the inputs hold.

**The shapes that are absent rather than present.** The minimum week, the collections a document
holds no key for, the entry kind that binds no content, and each concession kind's own fields.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import MISSING, fields
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_api.solving.snapshots import (
    FORM,
    INPUTS,
    SNAPSHOT_FORM,
    UnencodableInput,
    as_snapshot,
)
from syncr_api.solving.stored_inputs import (
    FORMS,
    SNAPSHOT,
    UnreadableSnapshot,
    inputs_of,
    require_a_reader_for_every_field,
)
from syncr_domain.errors import DomainError
from syncr_domain.feasibility import DeadlineDemand
from syncr_domain.gaps import EmptySlotReason
from syncr_domain.habits import BindingSource, Duration
from syncr_domain.identity import (
    BindingKind,
    BindingRef,
    date_occurrence_key,
    index_occurrence_key,
)
from syncr_domain.intervals import Interval
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.plan import AdjustmentKind
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind, PreferenceStrength
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.tasks import Priority
from syncr_domain.templates import BindingTarget, TemplateEntryKind
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
from tests.plan_documents import (
    CAREER,
    FITNESS,
    INTERVIEW,
    WEEK,
    a_block_holding,
    a_document,
    a_slot,
    a_window,
    a_zone_map,
    at,
    between,
)

if TYPE_CHECKING:
    from dataclasses import Field

    from syncr_api.core.columns import JsonObject
    from syncr_domain.plan import PlanDocument

SPAN = Interval(at(0), at(0, day=7))
NOW = at(9.5, day=2)

A_ROUTINE = uuid4()
A_HABIT = uuid4()
A_TASK = uuid4()
AN_ENTRY = uuid4()
AN_ADJUSTMENT = uuid4()

# A rotation's own clause, so a stored plan carries the one clause field a fixed source leaves
# null: the cursor is where a rotation is up to, and only a rotation has one.
A_ROTATION_REASON = ReasonRecord((Bound(BindingSource.ROTATION, "fiction", cursor="2 of 3"),))


def a_week_holding_one_of_everything(**overrides: Any) -> SolveInputs:
    """One week's inputs with a member in every collection and every optional stated.

    Every optional is stated because of what the absent case costs a round trip: a field that is
    ``None`` on both sides is equal whether the reader read it or ignored it, so a week of nulls
    would let three of the six groups above pass on a reader that reads almost nothing. The absent
    case is driven separately, where its own equality is the point.
    """
    fields_of_the_week: dict[str, Any] = {
        "iso_week": WEEK,
        "span": SPAN,
        "now": NOW,
        "zone_by_date": a_zone_map(),
        "input_version": 41,
        "frame": (
            FrameEntry(
                routine_id=A_ROUTINE,
                occurrence_key=date_occurrence_key(WEEK.monday()),
                interval=between(23, 31),
                min_duration_minutes=360,
                flex_band_minutes=30,
                title="Sleep",
            ),
        ),
        "frame_overhang": (FrameOverhang(interval=between(0, 7), area_id=CAREER),),
        "anchors": (
            Anchor(anchor_id=INTERVIEW, interval=between(14, 16, day=2), title="Kontron Interview"),
        ),
        "shadow_blocks": (
            ShadowBlock(
                binding=BindingRef.for_anchor_prep(INTERVIEW),
                interval=between(13.5, 14, day=2),
                area_id=CAREER,
                title="prep · Kontron Interview",
                anchor_type_name="Interview",
                anchor_title="Kontron Interview",
            ),
        ),
        "forbidden_windows": (a_window(),),
        "dropped_legs": (
            a_slot(reason=EmptySlotReason.DROPPED_LEG, interval=between(16, 16.5, day=2)),
        ),
        "off_plan": (
            OffPlanPeriod(interval=between(9, 17, day=5), keep_frame=True, label="Amsterdam"),
        ),
        "template_entries": (a_concrete_entry(),),
        "habit_occurrences": (
            HabitOccurrence(
                binding=BindingRef.for_habit(A_HABIT, index=0),
                duration=Duration.elastic(min_minutes=30, max_minutes=90),
                area_id=FITNESS,
                title="Reading",
                binding_source=BindingSource.ROTATION,
                variant="fiction",
                is_debt=True,
            ),
        ),
        "eligible_tasks": (
            EligibleTask(
                binding=BindingRef.for_task(A_TASK, split_index=1),
                remaining_minutes=180,
                priority=Priority.HIGH,
                min_chunk_minutes=45,
                splittable=True,
                area_id=CAREER,
                title="Leetcode",
                deadline=at(17, day=4),
            ),
        ),
        "areas": (
            AreaBudget(
                area_id=CAREER,
                name="Career",
                floor_minutes=300,
                floor_reservation_minutes=180,
                declared_floor_minutes=360,
                target_minutes=600,
                placed_minutes=120,
                max_per_day_minutes=240,
            ),
        ),
        "preferences": (
            ResolvedPreference(
                owner=PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=CAREER),
                windows=(between(9, 12),),
                strength=PreferenceStrength.STRONG,
                preferred_duration_minutes=60,
            ),
        ),
        "pins": (
            Pin(
                binding=BindingRef.for_task(A_TASK, split_index=2),
                interval=between(6.5, 7.5, day=1),
                pinned_on=WEEK.monday(),
                superseded_placement=between(18, 19, day=1),
                objective_delta=-4.25,
            ),
        ),
        "deadline_demands": (
            DeadlineDemand(
                deadline=at(17, day=4),
                remaining_minutes=180,
                area_id=CAREER,
                labels=("Leetcode",),
                contributors=((A_TASK, 180),),
            ),
        ),
        # Both concessions, because each kind sets one of the two optional halves and leaves the
        # other null: one member alone would drive `reductions` or `delta_minutes` but not both.
        "adjustments": (
            an_adjustment(AdjustmentKind.REDUCE_ROUTINE),
            an_adjustment(AdjustmentKind.BREACH_FLOOR),
        ),
        # The two documents differ, because they are different documents: the live plan is the
        # newest revision whatever its status and the baseline is the newest APPROVED one. A
        # reader taking one for the other would round-trip a week that agrees with itself.
        "live_plan": a_plan_stating_every_optional(unallocated_minutes=120),
        "churn_baseline": ChurnBaseline.approved(
            uuid4(), at(20, day=-1), a_plan_stating_every_optional(unallocated_minutes=45)
        ),
    }
    return SolveInputs(**(fields_of_the_week | overrides))


def a_plan_stating_every_optional(**overrides: Any) -> PlanDocument:
    """A stored plan with nothing left absent: every collection holds one, every optional is set.

    A block's optional halves arrive together or not at all, so the block is PINNED: a superseded
    placement and what replacing it cost are what the domain requires of a pin and forbids of
    anything else. It binds a task chunk for the same reason, since a chunk index is the one
    binding component only a task's identity may carry.

    Beside it, a made-up habit occurrence: the one block whose make-up mark can be true, which is
    what keeps that key load-bearing in the walk below.
    """
    pinned = a_block_holding(
        BindingRef.for_task(A_TASK, split_index=1),
        between(9, 10),
        pinned=True,
        superseded_placement=between(18, 19),
        objective_delta=-2.5,
        split_count=2,
        reason=A_ROTATION_REASON,
    )
    made_up = a_block_holding(
        BindingRef.for_habit(A_HABIT, index=1),
        between(11, 12),
        make_up=True,
        reason=A_ROTATION_REASON,
    )
    stated: dict[str, Any] = {
        "blocks": (pinned, made_up),
        "forbidden_windows": (a_window(),),
        "empty_slots": (a_slot(),),
        "adjustments": (AN_ADJUSTMENT,),
    }
    return a_document(**(stated | overrides))


def a_concrete_entry(**overrides: Any) -> MaterializedEntry:
    """A template entry naming its content, which is the kind that carries both optionals."""
    stated: dict[str, Any] = {
        "entry_id": AN_ENTRY,
        "occurrence_key": date_occurrence_key(WEEK.monday()),
        "kind": TemplateEntryKind.CONCRETE,
        "interval": between(7, 7.25),
        "flex_band_minutes": 15,
        "area_id": FITNESS,
        "day_type_name": "Weekday",
        "title": "Wake Up",
        "binding": EntryBinding(target=BindingTarget.ROUTINE, entity_id=A_ROUTINE),
    }
    return MaterializedEntry(**(stated | overrides))


def an_adjustment(kind: AdjustmentKind) -> WeekAdjustment:
    """One concession of each kind, carrying the fields that kind actually sets.

    ``reductions`` is per-date minutes for a routine reduction and empty for the other three, and
    ``delta_minutes`` is set for a floor breach and null for the other three, so the two optional
    halves are driven by the kind rather than both being filled on one value nothing produces.
    """
    return WeekAdjustment(
        adjustment_id=uuid4(),
        kind=kind,
        target_id=uuid4(),
        reductions=(
            {WEEK.monday(): 30, WEEK.dates()[2]: 15}
            if kind is AdjustmentKind.REDUCE_ROUTINE
            else {}
        ),
        delta_minutes=45 if kind is AdjustmentKind.BREACH_FLOOR else None,
    )


def a_week_stating_no_optional(**overrides: Any) -> SolveInputs:
    """The inputs a week has before anything is resolved into it: the five that have no default."""
    stated: dict[str, Any] = {
        "iso_week": WEEK,
        "span": SPAN,
        "now": NOW,
        "zone_by_date": a_zone_map(),
        "input_version": 1,
    }
    return SolveInputs(**(stated | overrides))


def corrupted(week: SolveInputs, mutate: Any) -> JsonObject:
    """One snapshot with one thing wrong with it, deep-copied so no other case sees the edit."""
    snapshot = deepcopy(as_snapshot(week))
    mutate(snapshot[INPUTS])
    return snapshot


# --------------------------------------------------------------------------------
# A round trip is an equality
# --------------------------------------------------------------------------------


def test_a_week_holding_one_of_everything_round_trips_to_the_same_value() -> None:
    week = a_week_holding_one_of_everything()

    assert inputs_of(as_snapshot(week)) == week


@pytest.mark.parametrize("named", [field.name for field in fields(SolveInputs)])
def test_every_field_round_trips_to_the_same_value(named: str) -> None:
    """The whole-value equality above, per field, so a field that comes back wrong names itself.

    The parametrization is the dataclass's own field list, so a field added to the inputs arrives
    here without this file being edited.
    """
    week = a_week_holding_one_of_everything()

    read = inputs_of(as_snapshot(week))

    assert getattr(read, named) == getattr(week, named)


def test_the_seed_a_solve_would_resolve_ties_with_round_trips() -> None:
    """The derived value the reproduction turns on, which no field carries.

    A snapshot exists to be solved again, and two assemblies that agree on every field but not on
    the seed do not produce the same plan. It is derived from the week and the input version, so
    this is what says both survived as themselves rather than as something that compares equal.
    """
    week = a_week_holding_one_of_everything()

    assert inputs_of(as_snapshot(week)).seed == week.seed


def test_the_probe_reads_the_rebuilt_week_the_same_way() -> None:
    """The projection every capacity figure comes from, over the rebuilt value.

    ``for_probe()`` is where the netted quantities and the scope split are read, so a field that
    round-tripped as an equal value but a different shape would surface here rather than in a
    later reproduction.
    """
    week = a_week_holding_one_of_everything()

    assert inputs_of(as_snapshot(week)).for_probe() == week.for_probe()


# --------------------------------------------------------------------------------
# The equality is only worth what the week is
# --------------------------------------------------------------------------------


def test_the_week_holds_a_member_of_every_collection() -> None:
    """The first control: a collection left empty round-trips whether it is read or ignored."""
    week = a_week_holding_one_of_everything()

    empty = [
        field.name
        for field in fields(SolveInputs)
        if _stated_default(field) == () and not getattr(week, field.name)
    ]

    assert not empty, f"these collections hold no member, so their reader is unexercised: {empty}"


def test_the_week_states_a_value_every_defaulting_field_would_not_default_to() -> None:
    """The second control, and the one the whole-object equality depends on.

    A field whose stored value equals its default is equal on both sides whether the reader read
    it or dropped it, which is the shape an equality assertion cannot fail on.
    """
    week = a_week_holding_one_of_everything()

    defaulted = [
        field.name
        for field in fields(SolveInputs)
        if _stated_default(field) is not MISSING
        and getattr(week, field.name) == _stated_default(field)
    ]

    assert not defaulted, f"these fields sit at their default, so nothing bites there: {defaulted}"


def _stated_default(field: Field[Any]) -> Any:
    """What a field arrives at when the document states nothing for it, however it is declared.

    A factory rather than a value is the mandatory declaration for a mutable default, so a census
    reading ``field.default`` alone is blind to exactly the fields most likely to be added next: it
    reads ``MISSING`` for them and reports them as having no default to sit at.
    """
    if field.default is not MISSING:
        return field.default
    if field.default_factory is not MISSING:
        return field.default_factory()
    return MISSING


# The two stored keys no week can make load-bearing, and the reason is one rule: a chunk index is
# part of a TASK's identity and the domain refuses it on any other kind, so a shadow block's and a
# habit occurrence's bindings hold null there in every document that can exist. The same field is
# driven where it can be set, on a task's own binding and on a pinned block's.
ABSENT_BY_INVARIANT = frozenset(
    {
        "shadow_blocks[].binding.split_index",
        "habit_occurrences[].binding.split_index",
    }
)

KINDS_THAT_CANNOT_CARRY_A_CHUNK_INDEX = (
    (BindingKind.ANCHOR_PREP, ""),
    (BindingKind.HABIT, index_occurrence_key(0)),
)


def test_every_stored_key_changes_what_the_reader_rebuilds() -> None:
    """The third control, at every depth: a key the reader ignores is a field it silently defaults.

    Driven over the document the writer produced rather than over a list of paths, so a field added
    to any member type is covered the day the walk stores it. Dropping a key has to change the value
    the read produces, or be refused; a key whose absence changes nothing is a key nothing reads.

    Stated over the shape a path has rather than over each concrete position, because a collection
    holding two members states one shape twice: what has to be load-bearing is the FIELD, and a
    position where it is legitimately null says nothing about whether it is read.
    """
    faithful = as_snapshot(a_week_holding_one_of_everything())

    ignored = {
        shape
        for shape, paths in _shapes(faithful[INPUTS]).items()
        if not any(_drop_bites(faithful, path) for path in paths)
    }

    assert ignored == ABSENT_BY_INVARIANT


@pytest.mark.parametrize(("kind", "key"), KINDS_THAT_CANNOT_CARRY_A_CHUNK_INDEX)
def test_the_two_keys_no_document_can_exercise_are_refused_by_the_domain(
    kind: BindingKind, key: str
) -> None:
    """The other edge of that exclusion: the value that would make those keys bite is unbuildable.

    Without this the exclusion above is a list of keys nothing checks, which is how a reader that
    genuinely ignores one would join it unnoticed.
    """
    with pytest.raises(DomainError, match="chunk"):
        BindingRef(kind, A_TASK, key, 1)


def _shapes(stored: JsonObject) -> dict[str, list[str]]:
    """Every key path a document holds, grouped by the shape it has with its positions erased."""
    grouped: dict[str, list[str]] = {}
    for path in _paths(stored):
        grouped.setdefault(re.sub(r"\[\d+\]", "[]", path), []).append(path)
    return grouped


def _paths(stored: object, prefix: str = "") -> list[str]:
    """Every key path a stored document holds, mappings and array members alike."""
    if isinstance(stored, dict):
        return [
            path
            for key, held in stored.items()
            for path in [f"{prefix}{key}", *_paths(held, f"{prefix}{key}.")]
        ]
    if isinstance(stored, list):
        return [
            path
            for position, held in enumerate(stored)
            for path in _paths(held, f"{prefix.rstrip('.')}[{position}].")
        ]
    return []


def _drop_bites(faithful: JsonObject, path: str) -> bool:
    """Whether dropping one key changes what the read produces, or is refused outright."""
    snapshot = deepcopy(faithful)
    _drop(snapshot[INPUTS], path)
    try:
        return inputs_of(snapshot) != inputs_of(faithful)
    except (StoredDocumentCorrupt, UnreadableSnapshot):
        return True


def _drop(stored: Any, path: str) -> None:
    """Remove the value ``path`` names from a stored document, in place."""
    walked: Any = stored
    steps = path.split(".")
    for step in steps[:-1]:
        walked = _stepped(walked, step)
    key, position = _keyed(steps[-1])
    if position is None:
        del walked[key]
    else:
        del _stepped(walked, steps[-1])[key]


def _stepped(stored: Any, step: str) -> Any:
    key, position = _keyed(step)
    held = stored[key] if key else stored
    return held if position is None else held[position]


def _keyed(step: str) -> tuple[str, int | None]:
    """One step of a path, as its key and the array position it selects, if any."""
    if not step.endswith("]"):
        return step, None
    key, _, index = step[:-1].partition("[")
    return key, int(index)


# --------------------------------------------------------------------------------
# The other direction, which is the stronger one
# --------------------------------------------------------------------------------


def test_the_stored_form_survives_being_read_and_written_again() -> None:
    """What a re-write of a stored snapshot produces, which is the comparison values cannot make.

    An equality of values passes for a writer that omits a key the reader defaults and for a
    reader that ignores a key the writer emits. Comparing the two stored forms is what refuses
    both, and it is a comparison of mappings rather than of text because the column is JSONB and
    key order is not a fact the document holds.
    """
    written = as_snapshot(a_week_holding_one_of_everything())

    again = as_snapshot(inputs_of(written))

    assert again == written


# --------------------------------------------------------------------------------
# A field the value has and this module holds no form for
# --------------------------------------------------------------------------------


def test_every_field_of_the_inputs_has_a_stored_form() -> None:
    require_a_reader_for_every_field(_fields_with_a_form())


def test_a_read_refuses_while_a_field_has_no_stored_form(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard at the call site rather than on its own, which is where it has to be to bite.

    A guard tested only by calling it directly is a guard the read can stop consulting with nothing
    going red, and the read is the only place it protects anything.
    """
    snapshot = as_snapshot(a_week_holding_one_of_everything())
    monkeypatch.setattr("syncr_api.solving.stored_inputs.FORMS", FORMS[:-1])

    with pytest.raises(UnreadableSnapshot, match="churn_baseline"):
        inputs_of(snapshot)


def test_a_field_with_no_stored_form_refuses_the_read() -> None:
    """The refusal driven from a set this module does not hold, so the guard has a broken input."""
    named = {field.name for field in fields(SolveInputs)} - {"pins"}

    with pytest.raises(UnreadableSnapshot, match="pins"):
        require_a_reader_for_every_field(named)


def test_a_stored_form_naming_no_field_refuses_the_read() -> None:
    """The other edge: a form left by a field that has gone is not a read that still works."""
    named = {field.name for field in fields(SolveInputs)} | {"tenant_id"}

    with pytest.raises(UnreadableSnapshot, match="tenant_id"):
        require_a_reader_for_every_field(named)


def test_the_stated_forms_are_the_fields_in_the_order_the_value_declares_them() -> None:
    """The floor under the two refusals above, which two empty sets would satisfy."""
    assert _fields_with_a_form() == [field.name for field in fields(SolveInputs)]
    assert {"iso_week", "span", "now", "live_plan", "churn_baseline"} <= set(_fields_with_a_form())


def _fields_with_a_form() -> list[str]:
    return [named for named, _ in FORMS]


# --------------------------------------------------------------------------------
# A stored form that breaks a member's invariant says so where it is read
# --------------------------------------------------------------------------------


def _a_naive_instant(stored: JsonObject) -> None:
    stored["now"] = "2026-02-11T09:30:00"


def _a_week_that_does_not_exist(stored: JsonObject) -> None:
    stored["iso_week"] = "2026-W99"


def _a_day_with_no_zone(stored: JsonObject) -> None:
    del stored["zone_by_date"]["2026-02-15"]


def _a_zone_that_is_not_text(stored: JsonObject) -> None:
    stored["zone_by_date"]["2026-02-15"] = 0


def _a_span_that_covers_no_time(stored: JsonObject) -> None:
    stored["span"]["end"] = stored["span"]["start"]


def _an_overhang_outside_the_span(stored: JsonObject) -> None:
    stored["frame_overhang"][0]["interval"]["start"] = "2026-02-08T22:00:00+00:00"


def _an_overhang_that_is_not_a_span(stored: JsonObject) -> None:
    stored["frame_overhang"][0] = "the night before"


def _a_version_that_is_a_boolean(stored: JsonObject) -> None:
    stored["input_version"] = True


def _a_frame_entry_with_no_title(stored: JsonObject) -> None:
    del stored["frame"][0]["title"]


def _an_anchor_that_is_not_an_object(stored: JsonObject) -> None:
    stored["anchors"][0] = "Kontron Interview"


def _a_shadow_block_keyed_by_a_date(stored: JsonObject) -> None:
    stored["shadow_blocks"][0]["binding"]["occurrence_key"] = "2026-02-09"


def _a_scope_that_names_no_areas(stored: JsonObject) -> None:
    stored["forbidden_windows"][0]["forbidden_area_ids"] = []


def _a_dropped_leg_reason_nothing_produces(stored: JsonObject) -> None:
    stored["dropped_legs"][0]["reason"] = "vanished"


def _a_forbidden_kind_nothing_produces(stored: JsonObject) -> None:
    stored["forbidden_windows"][0]["kind"] = "errand"


def _an_off_plan_bound_off_the_grid(stored: JsonObject) -> None:
    stored["off_plan"][0]["interval"]["start"] = "2026-02-14T09:07:00+00:00"


def _a_concrete_entry_naming_no_content(stored: JsonObject) -> None:
    stored["template_entries"][0]["binding"] = None


def _a_slot_entry_naming_content(stored: JsonObject) -> None:
    stored["template_entries"][0]["kind"] = "slot"


def _an_entry_target_nothing_reads(stored: JsonObject) -> None:
    stored["template_entries"][0]["binding"]["target"] = "errand"


def _a_duration_that_runs_backwards(stored: JsonObject) -> None:
    stored["habit_occurrences"][0]["duration"]["max_minutes"] = 15


def _a_duration_off_the_grid(stored: JsonObject) -> None:
    stored["habit_occurrences"][0]["duration"]["min_minutes"] = 37


def _a_habit_keyed_by_a_date(stored: JsonObject) -> None:
    stored["habit_occurrences"][0]["binding"]["occurrence_key"] = "2026-02-09"


def _a_binding_source_nothing_produces(stored: JsonObject) -> None:
    stored["habit_occurrences"][0]["binding_source"] = "guessed"


def _a_task_entity_that_is_not_an_identifier(stored: JsonObject) -> None:
    stored["eligible_tasks"][0]["binding"]["entity_id"] = "leetcode"


def _a_priority_nothing_produces(stored: JsonObject) -> None:
    stored["eligible_tasks"][0]["priority"] = "whenever"


def _a_chunk_index_below_zero(stored: JsonObject) -> None:
    stored["eligible_tasks"][0]["binding"]["split_index"] = -1


def _minutes_that_are_text(stored: JsonObject) -> None:
    stored["areas"][0]["floor_minutes"] = "300"


def _a_strength_nothing_produces(stored: JsonObject) -> None:
    stored["preferences"][0]["strength"] = "firm"


def _a_preference_window_that_is_not_an_array(stored: JsonObject) -> None:
    stored["preferences"][0]["windows"] = {"0": {"start": "x", "end": "y"}}


def _a_pinned_on_that_is_not_a_date(stored: JsonObject) -> None:
    stored["pins"][0]["pinned_on"] = "monday"


def _a_demand_that_names_no_task(stored: JsonObject) -> None:
    stored["deadline_demands"][0]["labels"] = []


def _a_demand_below_zero(stored: JsonObject) -> None:
    stored["deadline_demands"][0]["remaining_minutes"] = -30


def _a_demand_whose_pairs_do_not_add_up(stored: JsonObject) -> None:
    stored["deadline_demands"][0]["contributors"][0][1] = 90


def _a_concession_kind_nothing_produces(stored: JsonObject) -> None:
    stored["adjustments"][0]["kind"] = "work_the_weekend"


def _a_reduction_keyed_by_a_weekday(stored: JsonObject) -> None:
    stored["adjustments"][0]["reductions"]["monday"] = stored["adjustments"][0]["reductions"].pop(
        "2026-02-09"
    )


def _two_live_plan_blocks_sharing_an_identity(stored: JsonObject) -> None:
    stored["live_plan"]["blocks"].append(deepcopy(stored["live_plan"]["blocks"][0]))


def _a_live_plan_block_with_no_title(stored: JsonObject) -> None:
    stored["live_plan"]["blocks"][0]["title"] = ""


def _a_baseline_plan_no_revision_names(stored: JsonObject) -> None:
    stored["churn_baseline"]["revision_id"] = None
    stored["churn_baseline"]["approved_at"] = None


def _a_baseline_with_no_instant_of_assent(stored: JsonObject) -> None:
    stored["churn_baseline"]["approved_at"] = None


def _a_baseline_document_that_is_not_an_object(stored: JsonObject) -> None:
    stored["churn_baseline"]["document"] = "the plan you approved"


REFUSALS = [
    pytest.param(_a_naive_instant, "now", "UTC offset", id="an instant with no offset"),
    pytest.param(_a_week_that_does_not_exist, "iso_week", "W99", id="a week that does not exist"),
    pytest.param(_a_day_with_no_zone, "inputs", "zone", id="a day with no zone"),
    pytest.param(_a_zone_that_is_not_text, "zone_by_date", "text", id="a zone that is a number"),
    pytest.param(_a_span_that_covers_no_time, "span", "start", id="a span covering no time"),
    pytest.param(_an_overhang_outside_the_span, "inputs", "outside", id="an overhang outside"),
    pytest.param(
        _an_overhang_that_is_not_a_span, "frame_overhang[0]", "an object", id="an overhang as text"
    ),
    pytest.param(
        _a_version_that_is_a_boolean, "input_version", "whole", id="a version that is a flag"
    ),
    pytest.param(
        _a_frame_entry_with_no_title, "frame[0].title", "text", id="a frame entry unnamed"
    ),
    pytest.param(
        _an_anchor_that_is_not_an_object, "anchors[0]", "an object", id="an anchor as text"
    ),
    pytest.param(
        _a_shadow_block_keyed_by_a_date,
        "shadow_blocks[0]",
        "occurrence",
        id="a shadow keyed wrongly",
    ),
    pytest.param(
        _a_scope_that_names_no_areas, "forbidden_windows[0]", "names", id="a scope naming no Areas"
    ),
    pytest.param(
        _a_forbidden_kind_nothing_produces,
        "forbidden_windows[0].kind",
        "not one of",
        id="a forbidden kind nothing produces",
    ),
    pytest.param(
        _a_dropped_leg_reason_nothing_produces,
        "dropped_legs[0].reason",
        "not one of",
        id="a dropped-leg reason nothing produces",
    ),
    pytest.param(_an_off_plan_bound_off_the_grid, "off_plan[0]", "grid", id="an off-plan bound"),
    pytest.param(
        _a_concrete_entry_naming_no_content,
        "template_entries[0]",
        "binding",
        id="a concrete entry naming no content",
    ),
    pytest.param(
        _a_slot_entry_naming_content, "template_entries[0]", "bound", id="a slot naming content"
    ),
    pytest.param(
        _an_entry_target_nothing_reads,
        "template_entries[0].binding.target",
        "not one of",
        id="an entry target nothing reads",
    ),
    pytest.param(
        _a_duration_that_runs_backwards,
        "habit_occurrences[0]",
        "backwards",
        id="a duration that runs backwards",
    ),
    pytest.param(
        _a_duration_off_the_grid, "habit_occurrences[0]", "grid", id="a duration off the grid"
    ),
    pytest.param(
        _a_habit_keyed_by_a_date, "habit_occurrences[0]", "occurrence", id="a habit keyed by a date"
    ),
    pytest.param(
        _a_binding_source_nothing_produces,
        "habit_occurrences[0].binding_source",
        "not one of",
        id="a binding source nothing produces",
    ),
    pytest.param(
        _a_task_entity_that_is_not_an_identifier,
        "eligible_tasks[0].binding.entity_id",
        "identifier",
        id="an entity that is not an identifier",
    ),
    pytest.param(
        _a_priority_nothing_produces,
        "eligible_tasks[0].priority",
        "not one of",
        id="a priority nothing produces",
    ),
    pytest.param(
        _a_chunk_index_below_zero,
        "eligible_tasks[0]",
        "counts from zero",
        id="a chunk index below zero",
    ),
    pytest.param(_minutes_that_are_text, "areas[0].floor_minutes", "whole", id="minutes as text"),
    pytest.param(
        _a_strength_nothing_produces,
        "preferences[0].strength",
        "not one of",
        id="a strength nothing produces",
    ),
    pytest.param(
        _a_preference_window_that_is_not_an_array,
        "preferences[0].windows",
        "an array",
        id="windows that are an object",
    ),
    pytest.param(
        _a_pinned_on_that_is_not_a_date, "pins[0].pinned_on", "local date", id="a pin date in words"
    ),
    pytest.param(
        _a_demand_that_names_no_task, "deadline_demands[0]", "by name", id="a demand naming no task"
    ),
    pytest.param(
        _a_demand_below_zero, "deadline_demands[0]", "outstanding", id="a demand below zero"
    ),
    pytest.param(
        _a_demand_whose_pairs_do_not_add_up,
        "deadline_demands[0]",
        "adding",
        id="a demand whose pairs disagree with its total",
    ),
    pytest.param(
        _a_concession_kind_nothing_produces,
        "adjustments[0].kind",
        "not one of",
        id="a concession kind nothing produces",
    ),
    pytest.param(
        _a_reduction_keyed_by_a_weekday,
        "adjustments[0].reductions",
        "local date",
        id="a reduction keyed by a weekday",
    ),
    pytest.param(
        _two_live_plan_blocks_sharing_an_identity,
        "live_plan",
        "share the identity",
        id="two live plan blocks sharing an identity",
    ),
    pytest.param(
        _a_live_plan_block_with_no_title,
        "live_plan: blocks[0]",
        "title",
        id="a live plan block with no title",
    ),
    pytest.param(
        _a_baseline_plan_no_revision_names,
        "churn_baseline",
        "names the revision",
        id="a baseline plan no revision names",
    ),
    pytest.param(
        _a_baseline_with_no_instant_of_assent,
        "churn_baseline",
        "instant of assent",
        id="a baseline with no instant of assent",
    ),
    pytest.param(
        _a_baseline_document_that_is_not_an_object,
        "churn_baseline.document",
        "an object",
        id="a baseline document that is text",
    ),
]


@pytest.mark.parametrize(("mutate", "named", "stated"), REFUSALS)
def test_a_stored_form_that_cannot_be_rebuilt_is_refused(
    mutate: Any, named: str, stated: str
) -> None:
    """Every refusal names the field it came from, which is what a reproduction needs to be fixed.

    The field is asserted as well as the statement, because a corruption reported against the
    whole document says only that the week is unusable: a reader stating which member of which
    collection could not be rebuilt is the difference between an operator's ten minutes and a day.
    """
    snapshot = corrupted(a_week_holding_one_of_everything(), mutate)

    with pytest.raises(StoredDocumentCorrupt) as refused:
        inputs_of(snapshot)

    assert named in str(refused.value)
    assert stated in str(refused.value)


def test_the_week_every_refusal_is_driven_from_reads_before_it_is_corrupted() -> None:
    """The control on the parametrization: an already-illegal week passes each case wrongly."""
    week = a_week_holding_one_of_everything()

    assert inputs_of(as_snapshot(week)) == week


def test_every_collection_the_inputs_hold_is_named_by_a_refusal() -> None:
    """The control on the refusal set's reach: a collection with no case has an unexercised reader.

    Derived from the fields rather than counted, so a collection added to the inputs is uncovered
    here until a refusal names it.
    """
    named = [field.name for field in fields(SolveInputs)]

    unnamed = [name for name in named if name not in _fields_a_refusal_names()]

    assert not unnamed, f"no refusal is driven through these fields: {unnamed}"


def _fields_a_refusal_names() -> set[str]:
    """The field each refusal case is driven through, as the head of the path the case names.

    A set of names rather than a search through the joined text of every case. A field name that is
    a prefix of another field's path would otherwise count itself as covered: ``frame`` reads as
    named by ``frame_overhang[0]``, and the collection no refusal drives is the one this census
    exists to find. The head is taken at the first separator a path can hold, which is a dot for a
    member's own field, a bracket for a position, and a colon for a plan carried inside the value.
    """
    return {
        re.split(r"[.\[:]", case.values[1])[0]
        for case in REFUSALS
        if isinstance(case.values[1], str)
    }


# --------------------------------------------------------------------------------
# The shapes that are absent rather than present
# --------------------------------------------------------------------------------


def test_the_minimum_week_round_trips() -> None:
    """Inputs holding nothing but the five fields with no default, which is a legal assembly."""
    week = a_week_stating_no_optional()

    assert inputs_of(as_snapshot(week)) == week


def test_a_snapshot_holding_no_collection_reads_as_the_minimum_week() -> None:
    """A document written before a field existed holds no key for it, and holds none of them."""
    week = a_week_holding_one_of_everything()
    snapshot = deepcopy(as_snapshot(week))
    for field in fields(SolveInputs):
        if field.default is not MISSING or field.default_factory is not MISSING:
            snapshot[INPUTS].pop(field.name)

    assert inputs_of(snapshot) == a_week_stating_no_optional(input_version=week.input_version)


def test_a_slot_entry_that_binds_no_content_round_trips() -> None:
    """The entry kind whose two optional halves are both absent, which its invariant requires."""
    slot = a_concrete_entry(kind=TemplateEntryKind.SLOT, title=None, binding=None)
    week = a_week_holding_one_of_everything(template_entries=(slot,))

    assert inputs_of(as_snapshot(week)).template_entries == (slot,)


@pytest.mark.parametrize("kind", list(AdjustmentKind))
def test_every_concession_kind_round_trips_with_the_fields_it_sets(kind: AdjustmentKind) -> None:
    """Each kind's own optional halves, so neither is only ever driven at one of its two values."""
    adjustment = an_adjustment(kind)
    week = a_week_holding_one_of_everything(adjustments=(adjustment,))

    assert inputs_of(as_snapshot(week)).adjustments == (adjustment,)


def test_a_week_that_never_approved_a_revision_round_trips() -> None:
    """The baseline's other two states, which the week above cannot hold at the same time."""
    week = a_week_holding_one_of_everything(
        churn_baseline=ChurnBaseline.never_approved(), live_plan=None
    )

    read = inputs_of(as_snapshot(week))

    assert read == week
    assert read.churn_baseline.reason == ChurnBaseline.NEVER_APPROVED


def test_a_baseline_naming_a_revision_this_deployment_cannot_read_round_trips() -> None:
    """The third state: a revision named, its plan absent, and churn structurally unmeasurable."""
    week = a_week_holding_one_of_everything(
        churn_baseline=ChurnBaseline.approved(uuid4(), at(20, day=-1))
    )

    read = inputs_of(as_snapshot(week))

    assert read == week
    assert read.churn_baseline.reason == ChurnBaseline.APPROVED_UNREADABLE
    assert not read.churn_baseline.is_measured


# --------------------------------------------------------------------------------
# The envelope
# --------------------------------------------------------------------------------


def test_the_form_the_writer_states_is_the_form_the_reader_rebuilds() -> None:
    assert as_snapshot(a_week_stating_no_optional())[FORM] == SNAPSHOT_FORM


def test_a_snapshot_of_another_form_is_refused() -> None:
    """A document whose walk had a different shape is not one this reader can rebuild."""
    snapshot = dict(as_snapshot(a_week_holding_one_of_everything()))
    snapshot[FORM] = SNAPSHOT_FORM + 1

    with pytest.raises(StoredDocumentCorrupt, match=FORM):
        inputs_of(snapshot)


def test_a_form_two_shadow_block_is_refused_before_its_missing_fields_are_read() -> None:
    snapshot = deepcopy(as_snapshot(a_week_holding_one_of_everything()))
    snapshot[FORM] = 2
    shadow_block = snapshot[INPUTS]["shadow_blocks"][0]
    del shadow_block["anchor_type_name"]
    del shadow_block["anchor_title"]

    with pytest.raises(StoredDocumentCorrupt, match=r"form names 2 and this reader rebuilds 4"):
        inputs_of(snapshot)


def test_a_snapshot_stating_no_form_is_refused() -> None:
    snapshot = dict(as_snapshot(a_week_holding_one_of_everything()))
    del snapshot[FORM]

    with pytest.raises(StoredDocumentCorrupt, match="whole number"):
        inputs_of(snapshot)


def test_a_snapshot_whose_inputs_are_not_an_object_is_refused() -> None:
    with pytest.raises(StoredDocumentCorrupt, match=INPUTS):
        inputs_of({FORM: SNAPSHOT_FORM, INPUTS: []})


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param([], id="an array"),
        pytest.param("a snapshot", id="text"),
        pytest.param(7, id="a number"),
        pytest.param(None, id="a null column"),
        pytest.param((), id="an empty tuple"),
    ],
)
def test_a_snapshot_that_is_not_an_object_at_all_is_refused(stored: Any) -> None:
    """The envelope, refused the way every level below it is rather than indexed first.

    The column is nullable ``JSONB`` and nothing constrains its shape, so the first caller to hold
    what the column returned is the first thing to meet this. Indexed first, each of these answers a
    corrupt row with an ``AttributeError`` naming a Python type, which says nothing about the
    document and nothing an operator can act on.
    """
    with pytest.raises(StoredDocumentCorrupt, match=SNAPSHOT):
        inputs_of(stored)


def test_a_value_the_walk_holds_no_leaf_form_for_is_refused() -> None:
    """The writer's own guard, which nothing drove until this reader gave it a reason to exist.

    No field of the inputs is annotated as anything the leaf table misses, so the value driven here
    is one the annotations forbid: that is the point of the refusal rather than an argument against
    it. What it protects is the field a later member type adds, whose type reaches the walk before
    anyone has thought about how it is stored, and the alternative to refusing is a snapshot
    carrying that value's ``repr`` and reproducing nothing.
    """
    week = a_week_stating_no_optional(input_version=timedelta(minutes=15))

    with pytest.raises(UnencodableInput, match="timedelta"):
        as_snapshot(week)
