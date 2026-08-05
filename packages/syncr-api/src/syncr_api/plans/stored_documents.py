"""A stored plan document, read and written through the domain constructors.

``plan_revisions.document`` is authoritative: every scalar column beside it is re-derived from
it, the churn baseline is measured against it, and the projector writes the calendar from it.
So the pair of functions here is the whole boundary between a week as a value and a week as a
row, and both directions go through the same value types.

**Writing states the fields a value HAS, and no others.** ``Block.id``, ``.origin`` and
``.split_index`` are derived properties with no field to store, so nothing here writes one. A
stored id would be a cache of the derivation that can only disagree with it, and an origin and
its binding kind are two readings of one set, so storing either would let them drift. A test
reads the serialized form and asserts each key is absent.

**A block carries no week of its own either.** ``Block.iso_week`` is a field because the id is
derived from it, not because it varies inside a document: ``PlanDocument`` already refuses a
block from another week. So the week is written once, at the top, and every block is rebuilt
against it. Writing it per block would be a second statement of one fact, and the only thing a
second statement can do is disagree.

**Reading parses, and a row that cannot be rebuilt says so here.** JSON carries text where the
domain holds identifiers, instants, dates, and closed vocabularies, and every one of those value
types refuses a malformed component: a binding refuses an ``entity_id`` that is not a ``UUID``
and refuses an occurrence key that does not match its kind. A row breaking either is a corrupt
row, and the honest answer is that it describes no week rather than a value that pairs with
nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.stored_reasons import read_reason, stored_reason
from syncr_api.plans.stored_values import (
    read_date,
    read_flag,
    read_id,
    read_interval,
    read_list,
    read_mapping,
    read_member,
    read_minutes,
    read_optional_id,
    read_optional_interval,
    read_optional_minutes,
    read_optional_number,
    read_text,
    rebuilt,
    stored_date,
    stored_id,
    stored_interval,
)
from syncr_domain.gaps import (
    EmptySlot,
    EmptySlotReason,
    ForbiddenKind,
    ForbiddenScope,
    ForbiddenWindow,
)
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from syncr_api.core.columns import JsonDocument, JsonObject
    from syncr_domain.zones import Date, ZoneId

ISO_WEEK = "iso_week"
ZONE_BY_DATE = "zone_by_date"
DISCRETIONARY_MINUTES = "discretionary_minutes"
UNALLOCATED_MINUTES = "unallocated_minutes"
OVERSUBSCRIPTION_MINUTES = "oversubscription_minutes"
BLOCKS = "blocks"
FORBIDDEN_WINDOWS = "forbidden_windows"
EMPTY_SLOTS = "empty_slots"
ADJUSTMENTS = "adjustments"

INTERVAL = "interval"
BINDING = "binding"
TITLE = "title"
REASON = "reason"
AREA_ID = "area_id"
PINNED = "pinned"
SUPERSEDED_PLACEMENT = "superseded_placement"
OBJECTIVE_DELTA = "objective_delta"
SPLIT_COUNT = "split_count"

KIND = "kind"
ENTITY_ID = "entity_id"
OCCURRENCE_KEY = "occurrence_key"
SPLIT_INDEX = "split_index"

SCOPE = "scope"
FORBIDDEN_AREA_IDS = "forbidden_area_ids"
LABEL = "label"
ANCHOR_ID = "anchor_id"


def stored_document(document: PlanDocument) -> JsonObject:
    """One week's plan, as the object ``plan_revisions.document`` holds."""
    return {
        ISO_WEEK: str(document.iso_week),
        ZONE_BY_DATE: _stored_zones(document.zone_by_date),
        DISCRETIONARY_MINUTES: document.discretionary_minutes,
        UNALLOCATED_MINUTES: document.unallocated_minutes,
        OVERSUBSCRIPTION_MINUTES: document.oversubscription_minutes,
        BLOCKS: [_stored_block(block) for block in document.blocks],
        FORBIDDEN_WINDOWS: [_stored_window(window) for window in document.forbidden_windows],
        EMPTY_SLOTS: [_stored_slot(slot) for slot in document.empty_slots],
        ADJUSTMENTS: [stored_id(adjustment) for adjustment in document.adjustments],
    }


def plan_document(stored: JsonDocument) -> PlanDocument:
    """The week a stored document describes, or a stated refusal.

    Every part is rebuilt through its own constructor, so a document that reaches a caller has
    already satisfied every invariant the domain states about a week: seven zones, one block per
    identity, blocks of this week only, and figures that count minutes.
    """
    iso_week = rebuilt(
        lambda: IsoWeek.parse(read_text(stored.get(ISO_WEEK), field=ISO_WEEK)), field=ISO_WEEK
    )
    return rebuilt(
        lambda: PlanDocument(
            iso_week=iso_week,
            zone_by_date=_read_zones(stored.get(ZONE_BY_DATE)),
            discretionary_minutes=read_minutes(
                stored.get(DISCRETIONARY_MINUTES), field=DISCRETIONARY_MINUTES
            ),
            unallocated_minutes=read_minutes(
                stored.get(UNALLOCATED_MINUTES), field=UNALLOCATED_MINUTES
            ),
            oversubscription_minutes=read_minutes(
                stored.get(OVERSUBSCRIPTION_MINUTES), field=OVERSUBSCRIPTION_MINUTES
            ),
            blocks=_each(stored, BLOCKS, lambda one, at: _read_block(one, iso_week, field=at)),
            forbidden_windows=_each(stored, FORBIDDEN_WINDOWS, _read_window),
            empty_slots=_each(stored, EMPTY_SLOTS, _read_slot),
            adjustments=_each(stored, ADJUSTMENTS, lambda one, at: read_id(one, field=at)),
        ),
        field="the document",
    )


def _each[MemberT](
    stored: JsonDocument, key: str, read: Callable[[object, str], MemberT]
) -> tuple[MemberT, ...]:
    """One collection of a document, each member read under a field naming its position.

    The position is in the field name rather than left out, because a refusal has to say WHICH
    block of a stored week could not be rebuilt: a week holds hundreds and they are not named.
    """
    return tuple(
        read(member, f"{key}[{position}]")
        for position, member in enumerate(read_list(stored.get(key), field=key))
    )


def _stored_zones(zone_by_date: Mapping[Date, ZoneId]) -> JsonObject:
    return {stored_date(day): zone for day, zone in zone_by_date.items()}


def _read_zones(value: object) -> dict[Date, ZoneId]:
    stored = read_mapping(value, field=ZONE_BY_DATE)
    return {
        read_date(day, field=f"{ZONE_BY_DATE}[{day!r}]"): read_text(
            zone, field=f"{ZONE_BY_DATE}[{day!r}]"
        )
        for day, zone in stored.items()
    }


def _stored_block(block: Block) -> JsonObject:
    return {
        INTERVAL: stored_interval(block.interval),
        BINDING: stored_binding(block.binding),
        TITLE: block.title,
        REASON: stored_reason(block.reason),
        AREA_ID: None if block.area_id is None else stored_id(block.area_id),
        PINNED: block.pinned,
        SUPERSEDED_PLACEMENT: (
            None
            if block.superseded_placement is None
            else stored_interval(block.superseded_placement)
        ),
        OBJECTIVE_DELTA: block.objective_delta,
        SPLIT_COUNT: block.split_count,
    }


def _read_block(value: object, iso_week: IsoWeek, *, field: str) -> Block:
    stored = read_mapping(value, field=field)
    return rebuilt(
        lambda: Block(
            iso_week=iso_week,
            interval=read_interval(stored.get(INTERVAL), field=f"{field}.{INTERVAL}"),
            binding=read_binding(stored.get(BINDING), field=f"{field}.{BINDING}"),
            title=read_text(stored.get(TITLE), field=f"{field}.{TITLE}"),
            reason=read_reason(stored.get(REASON), field=f"{field}.{REASON}"),
            area_id=read_optional_id(stored.get(AREA_ID), field=f"{field}.{AREA_ID}"),
            pinned=read_flag(stored.get(PINNED), field=f"{field}.{PINNED}"),
            superseded_placement=read_optional_interval(
                stored.get(SUPERSEDED_PLACEMENT), field=f"{field}.{SUPERSEDED_PLACEMENT}"
            ),
            objective_delta=read_optional_number(
                stored.get(OBJECTIVE_DELTA), field=f"{field}.{OBJECTIVE_DELTA}"
            ),
            split_count=read_optional_minutes(
                stored.get(SPLIT_COUNT), field=f"{field}.{SPLIT_COUNT}"
            ),
        ),
        field=field,
    )


def stored_binding(binding: BindingRef) -> JsonObject:
    """One content identity, as the object a stored ``binding`` column holds.

    Public, because a binding is stored beside a document as well as inside one: a pin, an
    outcome, an edit event and a conflict each carry the identity of the block they name, and a
    second spelling of one identity is how two of those tables would come to disagree about which
    block they mean.
    """
    return {
        KIND: binding.kind.value,
        ENTITY_ID: stored_id(binding.entity_id),
        OCCURRENCE_KEY: binding.occurrence_key,
        SPLIT_INDEX: binding.split_index,
    }


def read_binding(value: object, *, field: str) -> BindingRef:
    """The content identity a stored object names, or a stated refusal."""
    stored = read_mapping(value, field=field)
    return BindingRef(
        kind=read_member(BindingKind, stored.get(KIND), field=f"{field}.{KIND}"),
        entity_id=read_id(stored.get(ENTITY_ID), field=f"{field}.{ENTITY_ID}"),
        occurrence_key=read_text(stored.get(OCCURRENCE_KEY), field=f"{field}.{OCCURRENCE_KEY}"),
        split_index=read_optional_minutes(stored.get(SPLIT_INDEX), field=f"{field}.{SPLIT_INDEX}"),
    )


def _stored_window(window: ForbiddenWindow) -> JsonObject:
    return {
        INTERVAL: stored_interval(window.interval),
        KIND: window.kind.value,
        SCOPE: window.scope.value,
        FORBIDDEN_AREA_IDS: [stored_id(area_id) for area_id in window.forbidden_area_ids],
        LABEL: window.label,
        ANCHOR_ID: stored_id(window.anchor_id),
    }


def _read_window(value: object, field: str) -> ForbiddenWindow:
    stored = read_mapping(value, field=field)
    areas = f"{field}.{FORBIDDEN_AREA_IDS}"
    return ForbiddenWindow(
        interval=read_interval(stored.get(INTERVAL), field=f"{field}.{INTERVAL}"),
        kind=read_member(ForbiddenKind, stored.get(KIND), field=f"{field}.{KIND}"),
        scope=read_member(ForbiddenScope, stored.get(SCOPE), field=f"{field}.{SCOPE}"),
        forbidden_area_ids=tuple(
            read_id(area_id, field=f"{areas}[{position}]")
            for position, area_id in enumerate(
                read_list(stored.get(FORBIDDEN_AREA_IDS), field=areas)
            )
        ),
        label=read_text(stored.get(LABEL), field=f"{field}.{LABEL}"),
        anchor_id=read_id(stored.get(ANCHOR_ID), field=f"{field}.{ANCHOR_ID}"),
    )


def _stored_slot(slot: EmptySlot) -> JsonObject:
    return {
        INTERVAL: stored_interval(slot.interval),
        AREA_ID: stored_id(slot.area_id),
        REASON: slot.reason.value,
    }


def _read_slot(value: object, field: str) -> EmptySlot:
    stored = read_mapping(value, field=field)
    return EmptySlot(
        interval=read_interval(stored.get(INTERVAL), field=f"{field}.{INTERVAL}"),
        area_id=read_id(stored.get(AREA_ID), field=f"{field}.{AREA_ID}"),
        reason=read_member(EmptySlotReason, stored.get(REASON), field=f"{field}.{REASON}"),
    )
