"""An edit context's stored form: written into ``edit_events.context``, and read back out of it.

**Both directions.** A serializer with no reader cannot be shown faithful: a field silently dropped
writes successfully forever, and this column is the one whose loss is unrecoverable. ``E5`` says
these rows are never pruned because they are the training corpus, which makes a dropped field a
permanent hole rather than a bug a later run repairs.

Nothing in this deployment reads a context back on a request path. The reader exists because the
fitter that will read one is offline and in another package: it reads this column, so the spelling
has to be stated somewhere both can be held to.

The keys are the field names, so the stored object and the value it came from read alike in a
``psql`` session and in a fitter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.edit_context import EditContext, RejectedWindow
from syncr_api.plans.errors import EditContextRejected, StoredDocumentCorrupt
from syncr_api.plans.stored_values import (
    read_flag,
    read_list,
    read_mapping,
    read_number,
    read_optional_id,
    read_optional_whole_number,
    read_text,
    read_whole_number,
    stored_id,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.core.columns import JsonDocument, JsonObject

CONTEXT = "edit_events.context"

WEEKDAY = "weekday"
ACCEPTED_START_MINUTE_OF_DAY = "accepted_start_minute_of_day"
PROPOSED_START_MINUTE_OF_DAY = "proposed_start_minute_of_day"
DURATION_MINUTES = "duration_minutes"
ZONE = "zone"

OBJECTIVE_BREAKDOWN = "objective_breakdown"
MEASUREMENT_DELTA = "measurement_delta"
DISCRETIONARY_MINUTES = "discretionary_minutes"
UNALLOCATED_MINUTES = "unallocated_minutes"
BLOCKS_IN_DAY = "blocks_in_day"
PINNED_BLOCKS_IN_WEEK = "pinned_blocks_in_week"

AREA_ID = "area_id"
AREA_FLOOR_MINUTES = "area_floor_minutes"
AREA_PLACED_MINUTES = "area_placed_minutes"
AREA_TARGET_MINUTES = "area_target_minutes"

ANCHOR_OFFSETS_MINUTES = "anchor_offsets_minutes"
FORBIDDEN_OFFSETS_MINUTES = "forbidden_offsets_minutes"
GAP_BEFORE_MINUTES = "gap_before_minutes"
GAP_AFTER_MINUTES = "gap_after_minutes"
ADJACENT_AREA_BEFORE = "adjacent_area_before"
ADJACENT_AREA_AFTER = "adjacent_area_after"

REJECTED_WINDOWS = "rejected_windows"
WAS_DEADLINE_CONSTRAINED = "was_deadline_constrained"
DAYS_UNTIL_DEADLINE = "days_until_deadline"
INSIDE_OFF_PLAN = "inside_off_plan"

OFFSET_MINUTES = "offset_minutes"
RULE = "rule"


def stored_context(context: EditContext) -> JsonObject:
    """One edit's feature snapshot, as the object its column holds."""
    return {
        WEEKDAY: context.weekday,
        ACCEPTED_START_MINUTE_OF_DAY: context.accepted_start_minute_of_day,
        PROPOSED_START_MINUTE_OF_DAY: context.proposed_start_minute_of_day,
        DURATION_MINUTES: context.duration_minutes,
        ZONE: context.zone,
        OBJECTIVE_BREAKDOWN: dict(context.objective_breakdown),
        MEASUREMENT_DELTA: (
            None if context.measurement_delta is None else dict(context.measurement_delta)
        ),
        DISCRETIONARY_MINUTES: context.discretionary_minutes,
        UNALLOCATED_MINUTES: context.unallocated_minutes,
        BLOCKS_IN_DAY: context.blocks_in_day,
        PINNED_BLOCKS_IN_WEEK: context.pinned_blocks_in_week,
        AREA_ID: None if context.area_id is None else stored_id(context.area_id),
        AREA_FLOOR_MINUTES: context.area_floor_minutes,
        AREA_PLACED_MINUTES: context.area_placed_minutes,
        AREA_TARGET_MINUTES: context.area_target_minutes,
        ANCHOR_OFFSETS_MINUTES: list(context.anchor_offsets_minutes),
        FORBIDDEN_OFFSETS_MINUTES: list(context.forbidden_offsets_minutes),
        GAP_BEFORE_MINUTES: context.gap_before_minutes,
        GAP_AFTER_MINUTES: context.gap_after_minutes,
        ADJACENT_AREA_BEFORE: _stored_area(context.adjacent_area_before),
        ADJACENT_AREA_AFTER: _stored_area(context.adjacent_area_after),
        REJECTED_WINDOWS: [_stored_window(one) for one in context.rejected_windows],
        WAS_DEADLINE_CONSTRAINED: context.was_deadline_constrained,
        DAYS_UNTIL_DEADLINE: context.days_until_deadline,
        INSIDE_OFF_PLAN: context.inside_off_plan,
    }


def read_context(stored: JsonDocument) -> EditContext:
    """The feature snapshot a stored object names, or a stated refusal.

    A refusal from the value type is restated as the corruption of a stored row, which is what
    :func:`~syncr_api.plans.stored_values.rebuilt` does for a document: one category of failure
    reads one way wherever stored plan state is read, and the refusal's own message is carried
    through because it already says which invariant fell.
    """
    try:
        return _context(stored)
    except EditContextRejected as rejected:
        raise StoredDocumentCorrupt(f"{CONTEXT} could not be rebuilt: {rejected}") from rejected


def _context(stored: JsonDocument) -> EditContext:
    return EditContext(
        weekday=read_whole_number(stored.get(WEEKDAY), field=_at(WEEKDAY)),
        accepted_start_minute_of_day=read_whole_number(
            stored.get(ACCEPTED_START_MINUTE_OF_DAY), field=_at(ACCEPTED_START_MINUTE_OF_DAY)
        ),
        proposed_start_minute_of_day=read_whole_number(
            stored.get(PROPOSED_START_MINUTE_OF_DAY), field=_at(PROPOSED_START_MINUTE_OF_DAY)
        ),
        duration_minutes=read_whole_number(
            stored.get(DURATION_MINUTES), field=_at(DURATION_MINUTES)
        ),
        zone=read_text(stored.get(ZONE), field=_at(ZONE)),
        objective_breakdown=_read_breakdown(stored.get(OBJECTIVE_BREAKDOWN)),
        measurement_delta=_read_measurement_delta(stored.get(MEASUREMENT_DELTA)),
        discretionary_minutes=read_whole_number(
            stored.get(DISCRETIONARY_MINUTES), field=_at(DISCRETIONARY_MINUTES)
        ),
        unallocated_minutes=read_whole_number(
            stored.get(UNALLOCATED_MINUTES), field=_at(UNALLOCATED_MINUTES)
        ),
        blocks_in_day=read_whole_number(stored.get(BLOCKS_IN_DAY), field=_at(BLOCKS_IN_DAY)),
        pinned_blocks_in_week=read_whole_number(
            stored.get(PINNED_BLOCKS_IN_WEEK), field=_at(PINNED_BLOCKS_IN_WEEK)
        ),
        area_id=read_optional_id(stored.get(AREA_ID), field=_at(AREA_ID)),
        area_floor_minutes=read_optional_whole_number(
            stored.get(AREA_FLOOR_MINUTES), field=_at(AREA_FLOOR_MINUTES)
        ),
        area_placed_minutes=read_whole_number(
            stored.get(AREA_PLACED_MINUTES), field=_at(AREA_PLACED_MINUTES)
        ),
        area_target_minutes=read_whole_number(
            stored.get(AREA_TARGET_MINUTES), field=_at(AREA_TARGET_MINUTES)
        ),
        anchor_offsets_minutes=_read_offsets(
            stored.get(ANCHOR_OFFSETS_MINUTES), ANCHOR_OFFSETS_MINUTES
        ),
        forbidden_offsets_minutes=_read_offsets(
            stored.get(FORBIDDEN_OFFSETS_MINUTES), FORBIDDEN_OFFSETS_MINUTES
        ),
        gap_before_minutes=read_whole_number(
            stored.get(GAP_BEFORE_MINUTES), field=_at(GAP_BEFORE_MINUTES)
        ),
        gap_after_minutes=read_whole_number(
            stored.get(GAP_AFTER_MINUTES), field=_at(GAP_AFTER_MINUTES)
        ),
        adjacent_area_before=read_optional_id(
            stored.get(ADJACENT_AREA_BEFORE), field=_at(ADJACENT_AREA_BEFORE)
        ),
        adjacent_area_after=read_optional_id(
            stored.get(ADJACENT_AREA_AFTER), field=_at(ADJACENT_AREA_AFTER)
        ),
        rejected_windows=tuple(
            _read_window(one)
            for one in read_list(stored.get(REJECTED_WINDOWS), field=_at(REJECTED_WINDOWS))
        ),
        was_deadline_constrained=read_flag(
            stored.get(WAS_DEADLINE_CONSTRAINED), field=_at(WAS_DEADLINE_CONSTRAINED)
        ),
        days_until_deadline=read_optional_whole_number(
            stored.get(DAYS_UNTIL_DEADLINE), field=_at(DAYS_UNTIL_DEADLINE)
        ),
        inside_off_plan=read_flag(stored.get(INSIDE_OFF_PLAN), field=_at(INSIDE_OFF_PLAN)),
    )


def _at(key: str) -> str:
    return f"{CONTEXT}.{key}"


def _stored_area(area_id: object) -> str | None:
    return None if area_id is None else stored_id(area_id)  # type: ignore[arg-type]


def _stored_window(window: RejectedWindow) -> JsonObject:
    return {
        OFFSET_MINUTES: window.offset_minutes,
        DURATION_MINUTES: window.duration_minutes,
        RULE: window.rule,
    }


def _read_window(value: object) -> RejectedWindow:
    stored = read_mapping(value, field=_at(REJECTED_WINDOWS))
    return RejectedWindow(
        offset_minutes=read_whole_number(
            stored.get(OFFSET_MINUTES), field=_at(f"{REJECTED_WINDOWS}.{OFFSET_MINUTES}")
        ),
        duration_minutes=read_whole_number(
            stored.get(DURATION_MINUTES), field=_at(f"{REJECTED_WINDOWS}.{DURATION_MINUTES}")
        ),
        rule=read_text(stored.get(RULE), field=_at(f"{REJECTED_WINDOWS}.{RULE}")),
    )


def _read_offsets(value: object, named: str) -> tuple[int, ...]:
    """A list of signed minute offsets, each read as a whole number so a string is refused."""
    return tuple(
        read_whole_number(one, field=_at(named)) for one in read_list(value, field=_at(named))
    )


def _read_breakdown(value: object) -> Mapping[str, float]:
    """The seven costs a stored breakdown names. Which seven is the value type's own guard."""
    return _read_terms(value, named=OBJECTIVE_BREAKDOWN)


def _read_measurement_delta(value: object) -> Mapping[str, float] | None:
    """The seven measurement differences a stored object names, or nothing because it names none.

    Absent is a reading rather than a corruption, and it is the only optional key in this column.
    These rows are never pruned, so every event written before the difference was measured has no
    key here; refusing them would make the corpus unreadable to keep one field non-optional.
    """
    if value is None:
        return None
    return _read_terms(value, named=MEASUREMENT_DELTA)


def _read_terms(value: object, *, named: str) -> Mapping[str, float]:
    stored = read_mapping(value, field=_at(named))
    return {
        read_text(term, field=_at(named)): read_number(cost, field=_at(f"{named}.{term}"))
        for term, cost in stored.items()
    }
