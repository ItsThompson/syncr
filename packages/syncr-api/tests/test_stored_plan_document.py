"""The boundary between a week as a value and a week as a stored row, driven in both directions.

``plan_revisions.document`` is authoritative and nothing in the tree read or wrote one until now,
so the two fixtures that stood in for this path were both malformed: a habit keyed by a date, which
``BindingRef`` refuses, and a 32-character block id where the derivation produces 64. They are what
a reader written from the fixtures would have produced, which is why the round trip is asserted
over a week holding one block of each of the seven origins rather than over one convenient block.

Six groups.

**A round trip is an equality.** Written and read back, a week is the same value, over all seven
origins, all six clause kinds, both gap types, and the optional halves of a block.

**What is NOT written.** An id, an origin, a chunk index and a per-block week are each derived or
already stated, so each is asserted absent from the serialized form. A stored id is a cache of the
derivation and can only disagree with it.

**A row that cannot be rebuilt says so where it is read.** Every component of an identity is a
closed form, and a stored row can break any of them, so each refusal is driven and asserted to name
the field rather than to resolve into a value that pairs with nothing.

**The vocabularies the stored forms rest on.** The clause discriminator is crossed against the
domain's own budget table in both directions, and the two vocabularies a ``bound`` source spans are
asserted disjoint, because one stored word has to name exactly one of them.

**The equality holds because both directions go through the constructors.** The round trip above is
run again against a producer that spells the document itself, and it has to go red: four spellings a
second producer plausibly chooses are driven through it, against a hand spelling that round-trips
before any of them is changed. The one choice no round trip can catch is driven too.

**The writer is the only producer.** A walk over the package's own source asserts that nothing else
assembles a mapping that could be filed as a document, because the reader takes the keys it knows
and ignores the rest: what a second producer stores beside them reads back clean.
"""

from __future__ import annotations

import ast
import shutil
from copy import deepcopy
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syncr_api.plans import stored_documents
from syncr_api.plans.derivation import DOCUMENT_ISO_WEEK_KEY
from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_api.plans.stored_documents import plan_document, stored_document
from syncr_api.plans.stored_reasons import CLAUSE_KIND, READERS
from syncr_domain.gaps import (
    EmptySlot,
    EmptySlotReason,
    ForbiddenKind,
    ForbiddenScope,
    ForbiddenWindow,
)
from syncr_domain.habits import BindingSource
from syncr_domain.identity import (
    BLOCK_ID_LENGTH,
    BindingKind,
    BindingRef,
    Origin,
    TransitLeg,
    binding_kind_of,
)
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import (
    CLAUSE_BUDGET,
    Blocked,
    Bound,
    ChurnBaseline,
    DerivationSource,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
    PlacedSource,
    ReasonRecord,
)
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from syncr_api.core.columns import JsonObject
    from syncr_domain.intervals import Interval
    from syncr_domain.reasons import Clause

WEEK = IsoWeek(2026, 7)
MONDAY = WEEK.monday()
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)
LONDON = "Europe/London"

CAREER = uuid4()
FITNESS = uuid4()
INTERVIEW = uuid4()
GYM = uuid4()
LEETCODE = uuid4()
SLEEP = uuid4()
SHOWER = uuid4()

A_BOUND_REASON = ReasonRecord((Bound(DerivationSource.ROUTINE, "Sleep · 23:00 + 8h"),))


def between(start_hour: float, end_hour: float, *, day: int = 0) -> Interval:
    from syncr_domain.intervals import Interval

    start = MONDAY_MIDNIGHT + timedelta(days=day, hours=start_hour)
    end = MONDAY_MIDNIGHT + timedelta(days=day, hours=end_hour)
    return Interval(start, end)


def a_binding(kind: BindingKind) -> BindingRef:
    """One legal binding per kind, each keyed the way its own derivation keys it."""
    match kind:
        case BindingKind.ROUTINE:
            return BindingRef.for_routine(SLEEP, on=MONDAY)
        case BindingKind.TEMPLATE_ENTRY:
            return BindingRef.for_template_entry(SHOWER, on=MONDAY)
        case BindingKind.HABIT:
            return BindingRef.for_habit(GYM, index=3)
        case BindingKind.TASK:
            return BindingRef.for_task(LEETCODE, split_index=1)
        case BindingKind.ANCHOR:
            return BindingRef.for_anchor(INTERVIEW)
        case BindingKind.ANCHOR_PREP:
            return BindingRef.for_anchor_prep(INTERVIEW)
        case BindingKind.ANCHOR_TRANSIT:
            return BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.BACK)


def a_block(origin: Origin, **overrides: Any) -> Block:
    """A block of one origin, carrying an Area exactly when that origin requires one."""
    binding = a_binding(binding_kind_of(origin))
    fields_of: dict[str, Any] = {
        "iso_week": WEEK,
        "interval": between(6, 7.5),
        "binding": binding,
        "title": f"{origin.value} · something",
        "reason": A_BOUND_REASON,
        "area_id": None if origin in {Origin.FRAME, Origin.ANCHOR} else CAREER,
        "split_count": 3 if binding.split_index is not None else None,
    }
    return Block(**(fields_of | overrides))


def a_window(**overrides: Any) -> ForbiddenWindow:
    fields_of: dict[str, Any] = {
        "interval": between(16.75, 18),
        "kind": ForbiddenKind.RECOVERY,
        "scope": ForbiddenScope.AREAS,
        "forbidden_area_ids": (CAREER, FITNESS),
        "label": "recovery · Kontron Interview",
        "anchor_id": INTERVIEW,
    }
    return ForbiddenWindow(**(fields_of | overrides))


def a_slot(**overrides: Any) -> EmptySlot:
    fields_of: dict[str, Any] = {
        "interval": between(19, 20),
        "area_id": CAREER,
        "reason": EmptySlotReason.NOT_SOLVED,
    }
    return EmptySlot(**(fields_of | overrides))


def a_document(**overrides: Any) -> PlanDocument:
    fields_of: dict[str, Any] = {
        "iso_week": WEEK,
        "zone_by_date": dict.fromkeys(WEEK.dates(), LONDON),
        "discretionary_minutes": 6000,
        "unallocated_minutes": 120,
        "oversubscription_minutes": 45,
        "blocks": (a_block(Origin.HABIT),),
        "forbidden_windows": (a_window(),),
        "empty_slots": (a_slot(),),
        "adjustments": (uuid4(),),
    }
    return PlanDocument(**(fields_of | overrides))


def a_week_of_every_origin() -> PlanDocument:
    """One block per origin, each at its own hour so no two share a span.

    Seven origins in one document is the shape the round trip has to cover, and it is also the
    shape that catches a reader keyed on one kind: each of the seven is keyed differently.
    """
    return a_document(
        blocks=tuple(
            a_block(origin, interval=between(hour, hour + 1))
            for hour, origin in enumerate(Origin, start=8)
        )
    )


def a_week_of_every_clause() -> PlanDocument:
    """One block carrying the whole clause budget: two rejections and one of each other kind."""
    reason = ReasonRecord(
        (
            Blocked(window=between(9, 10), rule="H4", detail="an anchor already holds it"),
            Blocked(window=between(10, 11), rule="H7", detail=None),
            Dominant(
                term="budget_deviation",
                share=0.625,
                baseline=ChurnBaseline(
                    revision_id=uuid4(), approved_at=MONDAY_MIDNIGHT - timedelta(days=2)
                ),
            ),
            Bound(source=BindingSource.ROTATION, selected="Gym · Legs", cursor="03"),
            Floor(
                area_id=FITNESS,
                declared_floor_minutes=180,
                floor_minutes=180,
                placed=90,
                of=180,
            ),
            Pinned(at=between(13, 14.5), pinned_on=date(2026, 2, 8)),
            InsteadOf(placement=between(6, 7.5), objective_delta=-4.25),
        )
    )
    pinned = a_block(
        Origin.HABIT,
        reason=reason,
        pinned=True,
        superseded_placement=between(6, 7.5),
        objective_delta=-4.25,
    )
    return a_document(blocks=(pinned,))


def corrupted(document: PlanDocument, mutate: Any) -> JsonObject:
    """A stored week with one part changed, so each refusal is driven from a legal row."""
    stored = deepcopy(stored_document(document))
    mutate(stored)
    return stored


# --------------------------------------------------------------------------------
# A round trip is an equality
# --------------------------------------------------------------------------------


def test_a_week_of_every_origin_round_trips_to_the_same_value() -> None:
    document = a_week_of_every_origin()

    assert plan_document(stored_document(document)) == document


def test_every_origin_is_covered_by_that_week() -> None:
    # The control on the assertion above: a week that happened to hold six origins would still
    # round-trip, and the seventh is exactly the one the vocabulary was missing a reader for.
    origins = {block.origin for block in a_week_of_every_origin().blocks}

    assert origins == set(Origin)


def test_a_block_carrying_the_whole_clause_budget_round_trips() -> None:
    document = a_week_of_every_clause()

    assert plan_document(stored_document(document)) == document


def test_a_predeclared_floor_clause_migrates_to_an_explicit_unavailable_declaration() -> None:
    stored = stored_document(a_week_of_every_clause())
    floor = _clause(stored, "floor")
    del floor["declared_floor_version"]
    del floor["declared_floor_minutes"]
    floor["floor_minutes"] = 90

    legacy = plan_document(stored)
    migrated = stored_document(legacy)

    assert plan_document(migrated) == legacy
    assert _clause(migrated, "floor") == {
        "kind": "floor",
        "area_id": str(FITNESS),
        "declared_floor_version": 1,
        "floor_minutes": 90,
        "placed": 90,
        "of": 180,
    }


def test_a_recorded_floor_clause_requires_its_declared_minutes() -> None:
    stored = stored_document(a_week_of_every_clause())
    del _clause(stored, "floor")["declared_floor_minutes"]

    with pytest.raises(StoredDocumentCorrupt, match="declared_floor_minutes"):
        plan_document(stored)


def test_every_clause_kind_is_covered_by_that_block() -> None:
    # The control on the assertion above, bounded by the domain's own table rather than by a list
    # here: a seventh clause kind is uncovered until this week holds one.
    (block,) = a_week_of_every_clause().blocks
    carried = {type(clause) for clause in block.reason.clauses}

    assert carried == set(CLAUSE_BUDGET)


def test_the_whole_clause_budget_survives_the_column_in_the_form_it_was_written_in() -> None:
    """The other direction, and the stronger one: what a re-write of a stored row produces.

    The round trip above compares VALUES, which passes for a writer that omits a key the reader
    defaults and for a reader that ignores a key the writer emits. What a stored row has to survive
    is being read and written again, so the comparison is between the two stored forms.

    Equality of the mapping rather than of a byte string, because the column is JSONB and Postgres
    does not preserve key order: for such a column, two mappings being equal IS what "the same
    bytes" can mean.
    """
    written = stored_document(a_week_of_every_clause())

    again = stored_document(plan_document(written))

    assert again == written
    (block,) = written["blocks"]
    assert len(block["reason"]["clauses"]) == len(CLAUSE_BUDGET) + 1


def test_a_week_with_no_gaps_and_no_concessions_round_trips() -> None:
    """The empty collections, which a reader that required each key would fail on."""
    document = a_document(forbidden_windows=(), empty_slots=(), adjustments=())

    assert plan_document(stored_document(document)) == document


def test_a_document_missing_every_optional_collection_reads_as_empty() -> None:
    """A row written before a collection existed holds no key for it, and holds none of them."""
    stored = stored_document(a_document())
    for key in ("blocks", "forbidden_windows", "empty_slots", "adjustments"):
        del stored[key]

    read = plan_document(stored)

    assert (read.blocks, read.forbidden_windows, read.empty_slots, read.adjustments) == (
        (),
        (),
        (),
        (),
    )


def test_a_window_forbidding_everything_round_trips() -> None:
    window = a_window(
        kind=ForbiddenKind.PREP_UNATTRIBUTED, scope=ForbiddenScope.ALL, forbidden_area_ids=()
    )
    document = a_document(forbidden_windows=(window,))

    assert plan_document(stored_document(document)) == document


@pytest.mark.parametrize("reason", list(EmptySlotReason), ids=[r.value for r in EmptySlotReason])
def test_every_empty_slot_reason_round_trips(reason: EmptySlotReason) -> None:
    document = a_document(empty_slots=(a_slot(reason=reason),))

    assert plan_document(stored_document(document)) == document


def test_an_instant_survives_a_zone_the_row_was_not_written_in() -> None:
    """A stored instant carries its offset, and reading normalizes to UTC as the algebra does."""
    stored = stored_document(a_document())
    stored["blocks"][0]["interval"]["start"] = "2026-02-09T07:00:00+01:00"

    read = plan_document(stored)

    assert read.blocks[0].interval.start == datetime(2026, 2, 9, 6, tzinfo=UTC)


def test_a_made_up_occurrence_round_trips_to_the_same_value() -> None:
    document = a_document(blocks=(a_block(Origin.HABIT, make_up=True),))

    assert plan_document(stored_document(document)) == document


def test_a_row_written_before_the_mark_existed_reads_as_a_fresh_occurrence() -> None:
    """The honest default: an expansion nobody recorded cannot be claimed as a discharge."""
    stored = stored_document(a_document())
    del stored["blocks"][0]["make_up"]

    read = plan_document(stored)

    assert not read.blocks[0].make_up


# --------------------------------------------------------------------------------
# What is not written
# --------------------------------------------------------------------------------


def test_no_stored_block_carries_an_id() -> None:
    """An id is a hash of the week and the binding, so a stored one can only disagree with it."""
    stored = stored_document(a_week_of_every_origin())

    assert all("id" not in block for block in stored["blocks"])


def test_no_stored_block_carries_an_origin_or_a_chunk_index() -> None:
    """Both are read from the binding, and the binding is what the id is derived from."""
    stored = stored_document(a_week_of_every_origin())

    assert all("origin" not in block for block in stored["blocks"])
    assert all("split_index" not in block for block in stored["blocks"])


def test_no_stored_block_carries_a_week_of_its_own() -> None:
    """The document states the week once, and a document refuses a block from another one."""
    stored = stored_document(a_week_of_every_origin())

    assert all("iso_week" not in block for block in stored["blocks"])


def test_a_stored_block_states_every_other_field_a_block_has() -> None:
    """Bounded by the inventory: a field added to ``Block`` is unwritten until it is named here.

    ``iso_week`` is the one field deliberately absent, so it is the one exclusion, and the derived
    properties are absent from ``fields()`` already: that is what makes them unstorable.
    """
    (stored,) = stored_document(a_document())["blocks"]
    declared = {field.name for field in fields(Block)} - {"iso_week"}

    assert set(stored) == declared


def test_a_stored_document_states_every_field_a_document_has() -> None:
    stored = stored_document(a_document())

    assert set(stored) == {field.name for field in fields(PlanDocument)}


# --------------------------------------------------------------------------------
# A row that cannot be rebuilt says so where it is read
# --------------------------------------------------------------------------------


def _keyed_by_a_date(stored: JsonObject) -> None:
    stored["blocks"][0]["binding"]["occurrence_key"] = "2026-02-09"


def _entity_is_not_an_identifier(stored: JsonObject) -> None:
    stored["blocks"][0]["binding"]["entity_id"] = "gym"


def _an_unknown_binding_kind(stored: JsonObject) -> None:
    stored["blocks"][0]["binding"]["kind"] = "errand"


def _an_unknown_clause_kind(stored: JsonObject) -> None:
    stored["blocks"][0]["reason"]["clauses"][0]["kind"] = "vibes"


def _an_unknown_bound_source(stored: JsonObject) -> None:
    _clause(stored, "bound")["source"] = "guessed"


def _a_share_above_the_whole(stored: JsonObject) -> None:
    _clause(stored, "dominant")["share"] = 1.5


def _a_reason_with_no_clause(stored: JsonObject) -> None:
    stored["blocks"][0]["reason"]["clauses"] = []


def _three_rejected_windows(stored: JsonObject) -> None:
    one = {
        "kind": "blocked",
        "window": {"start": "2026-02-09T09:00:00+00:00", "end": "2026-02-09T10:00:00+00:00"},
        "rule": "H4",
        "detail": None,
    }
    stored["blocks"][0]["reason"]["clauses"] = [one, deepcopy(one), deepcopy(one)]


def _a_naive_instant(stored: JsonObject) -> None:
    stored["blocks"][0]["interval"]["start"] = "2026-02-09T06:00:00"


def _a_reversed_span(stored: JsonObject) -> None:
    stored["blocks"][0]["interval"]["end"] = stored["blocks"][0]["interval"]["start"]


def _a_week_that_does_not_exist(stored: JsonObject) -> None:
    # 2027 holds 52 ISO weeks, because its first of January is a Friday. 2026 holds 53, so the
    # week that does not exist has to be named in a year that does not have one.
    stored["iso_week"] = "2027-W53"


def _a_missing_day(stored: JsonObject) -> None:
    del stored["zone_by_date"]["2026-02-11"]


def _a_negative_figure(stored: JsonObject) -> None:
    stored["unallocated_minutes"] = -1


def _minutes_that_are_a_boolean(stored: JsonObject) -> None:
    stored["discretionary_minutes"] = True


def _a_title_that_names_nothing(stored: JsonObject) -> None:
    stored["blocks"][0]["title"] = ""


def _a_scope_that_names_no_areas(stored: JsonObject) -> None:
    stored["forbidden_windows"][0]["forbidden_area_ids"] = []


def _a_slot_reason_no_reader_knows(stored: JsonObject) -> None:
    stored["empty_slots"][0]["reason"] = "gave_up"


def _a_pin_flag_that_is_not_a_boolean(stored: JsonObject) -> None:
    stored["blocks"][0]["pinned"] = "yes"


def _a_make_up_mark_that_is_not_a_boolean(stored: JsonObject) -> None:
    stored["blocks"][0]["make_up"] = "yes"


def _a_make_up_mark_on_content_that_is_never_expanded(stored: JsonObject) -> None:
    # A legal task block carrying the mark, spelled beside the habit block the week already holds:
    # the refusal is the domain's, not the reader's.
    (habit,) = stored["blocks"]
    stored["blocks"].append(
        {
            **habit,
            "binding": {**habit["binding"], "kind": "task", "occurrence_key": "00"},
            "make_up": True,
        }
    )


def _a_delta_that_is_text(stored: JsonObject) -> None:
    stored["blocks"][0]["objective_delta"] = "-4.25"


def _a_delta_that_is_not_finite(stored: JsonObject) -> None:
    stored["blocks"][0]["objective_delta"] = float("inf")
    _clause(stored, "instead_of")["objective_delta"] = float("inf")


def _blocks_that_are_not_an_array(stored: JsonObject) -> None:
    stored["blocks"] = {"0": stored["blocks"][0]}


def _a_binding_that_is_not_an_object(stored: JsonObject) -> None:
    stored["blocks"][0]["binding"] = "habit:00"


def _a_zone_that_is_not_text(stored: JsonObject) -> None:
    stored["zone_by_date"]["2026-02-09"] = 0


def _a_day_that_is_not_a_date(stored: JsonObject) -> None:
    stored["zone_by_date"]["monday"] = stored["zone_by_date"].pop("2026-02-09")


def _a_chunk_index_that_is_a_number_in_text(stored: JsonObject) -> None:
    stored["blocks"][0]["split_count"] = "3"


def _clause(stored: JsonObject, kind: str) -> JsonObject:
    """The one clause of this kind on the first block, so a mutation lands where it is read.

    Selected by kind rather than by position: the budget week holds seven clauses in one order,
    and a mutation aimed at a position would silently land on a clause that ignores the key.
    """
    found: list[JsonObject] = [
        clause for clause in stored["blocks"][0]["reason"]["clauses"] if clause["kind"] == kind
    ]
    assert len(found) == 1, f"the budget week holds {len(found)} {kind!r} clauses"
    return found[0]


REFUSALS = [
    pytest.param(_keyed_by_a_date, "occurrence key", id="a habit keyed by a date"),
    pytest.param(_entity_is_not_an_identifier, "entity_id", id="an entity that is not an id"),
    pytest.param(_an_unknown_binding_kind, "kind", id="a binding kind nothing produces"),
    pytest.param(_an_unknown_clause_kind, "clause", id="a clause kind with no template"),
    pytest.param(_an_unknown_bound_source, "determines nothing", id="a bound source"),
    pytest.param(_a_share_above_the_whole, "share", id="a share above the whole"),
    pytest.param(_a_reason_with_no_clause, "at least one clause", id="a reason with no clause"),
    pytest.param(_three_rejected_windows, "bounded per clause kind", id="over the clause budget"),
    pytest.param(_a_naive_instant, "UTC offset", id="an instant with no offset"),
    pytest.param(_a_reversed_span, "start < end", id="a span that covers no time"),
    pytest.param(_a_week_that_does_not_exist, "iso_week", id="a week that does not exist"),
    pytest.param(_a_missing_day, "zone", id="a day with no zone"),
    pytest.param(_a_negative_figure, "negative", id="a figure below zero"),
    pytest.param(_minutes_that_are_a_boolean, "whole number", id="minutes that are a boolean"),
    pytest.param(_a_title_that_names_nothing, "names nothing", id="a block with no title"),
    pytest.param(_a_scope_that_names_no_areas, "names", id="a scope that names no Areas"),
    pytest.param(_a_slot_reason_no_reader_knows, "reason", id="a slot reason nothing produces"),
    pytest.param(_a_pin_flag_that_is_not_a_boolean, "true or false", id="a pin flag that is text"),
    pytest.param(
        _a_make_up_mark_that_is_not_a_boolean,
        "true or false",
        id="a make-up mark that is text",
    ),
    pytest.param(
        _a_make_up_mark_on_content_that_is_never_expanded,
        "only a habit occurrence",
        id="a made-up block of another origin",
    ),
    pytest.param(_a_delta_that_is_text, "a number", id="an objective delta that is text"),
    pytest.param(_a_delta_that_is_not_finite, "finite", id="an objective delta that is infinite"),
    pytest.param(_blocks_that_are_not_an_array, "an array", id="blocks that are an object"),
    pytest.param(_a_binding_that_is_not_an_object, "an object", id="a binding that is text"),
    pytest.param(_a_zone_that_is_not_text, "text", id="a zone that is a number"),
    pytest.param(_a_day_that_is_not_a_date, "local date", id="a day that is not a date"),
    pytest.param(_a_chunk_index_that_is_a_number_in_text, "whole number", id="a count in text"),
]


@pytest.mark.parametrize(("mutate", "stated"), REFUSALS)
def test_a_stored_row_that_cannot_be_rebuilt_is_refused(mutate: Any, stated: str) -> None:
    stored = corrupted(a_week_of_every_clause(), mutate)

    with pytest.raises(StoredDocumentCorrupt, match=stated):
        plan_document(stored)


def test_the_week_of_every_clause_is_legal_before_it_is_corrupted() -> None:
    # The control on the parametrization above: every refusal is driven from THIS row, so a row
    # that was already illegal would make each of them pass for the wrong reason.
    document = a_week_of_every_clause()

    assert plan_document(stored_document(document)) == document


# --------------------------------------------------------------------------------
# The vocabularies the stored forms rest on
# --------------------------------------------------------------------------------


def test_every_clause_the_domain_allows_has_a_stored_word() -> None:
    assert set(CLAUSE_KIND) == set(CLAUSE_BUDGET)


def test_every_stored_word_has_a_reader() -> None:
    assert set(READERS) == set(CLAUSE_KIND.values())


def test_the_stored_words_are_distinct() -> None:
    assert len(set(CLAUSE_KIND.values())) == len(CLAUSE_KIND)


def test_the_three_vocabularies_a_bound_source_spans_are_disjoint() -> None:
    """One stored word has to name exactly one source, and nothing else makes that decidable."""
    spelled = [
        {member.value for member in vocabulary}
        for vocabulary in (DerivationSource, BindingSource, PlacedSource)
    ]

    assert sum(len(words) for words in spelled) == len(set().union(*spelled))


@pytest.mark.parametrize(
    "source",
    [*DerivationSource, *BindingSource, *PlacedSource],
    ids=[member.value for member in (*DerivationSource, *BindingSource, *PlacedSource)],
)
def test_every_bound_source_round_trips_to_its_own_vocabulary(source: Any) -> None:
    document = a_document(
        blocks=(a_block(Origin.HABIT, reason=ReasonRecord((Bound(source, "Gym · Legs"),))),)
    )

    read = plan_document(stored_document(document))
    (clause,) = read.blocks[0].reason.clauses

    assert isinstance(clause, Bound)
    assert clause.source is source


# --------------------------------------------------------------------------------
# The equality holds because both directions go through the constructors
# --------------------------------------------------------------------------------


def hand_spelled(document: PlanDocument) -> JsonObject:
    """One week's plan spelled here, key by key, rather than by ``stored_document``.

    Every key and every leaf form is written out rather than imported, because a producer that
    borrowed the writer's constants and its leaf codecs would not be a second producer at all. This
    spelling is as close as one gets: legal, and equal on the way back, which is what makes each
    single change below attributable to the change rather than to hand spelling anything.

    Covers the week of every origin, whose blocks each carry one ``bound`` clause.
    """
    return {
        "iso_week": str(document.iso_week),
        "zone_by_date": {day.isoformat(): zone for day, zone in document.zone_by_date.items()},
        "discretionary_minutes": document.discretionary_minutes,
        "unallocated_minutes": document.unallocated_minutes,
        "oversubscription_minutes": document.oversubscription_minutes,
        "blocks": [_spelled_block(block) for block in document.blocks],
        "forbidden_windows": [_spelled_window(window) for window in document.forbidden_windows],
        "empty_slots": [_spelled_slot(slot) for slot in document.empty_slots],
        "adjustments": [str(adjustment) for adjustment in document.adjustments],
    }


def _spelled_block(block: Block) -> JsonObject:
    superseded = block.superseded_placement
    return {
        "interval": _spelled_span(block.interval),
        "binding": {
            "kind": block.binding.kind.value,
            "entity_id": str(block.binding.entity_id),
            "occurrence_key": block.binding.occurrence_key,
            "split_index": block.binding.split_index,
        },
        "title": block.title,
        "reason": {"clauses": [_spelled_clause(clause) for clause in block.reason.clauses]},
        "area_id": None if block.area_id is None else str(block.area_id),
        "pinned": block.pinned,
        "superseded_placement": None if superseded is None else _spelled_span(superseded),
        "objective_delta": block.objective_delta,
        "split_count": block.split_count,
    }


def _spelled_clause(clause: Clause) -> JsonObject:
    """The one clause kind every block of the week of every origin carries."""
    assert isinstance(clause, Bound), clause
    return {
        "kind": "bound",
        "source": clause.source.value,
        "selected": clause.selected,
        "cursor": clause.cursor,
    }


def _spelled_window(window: ForbiddenWindow) -> JsonObject:
    return {
        "interval": _spelled_span(window.interval),
        "kind": window.kind.value,
        "scope": window.scope.value,
        "forbidden_area_ids": [str(area_id) for area_id in window.forbidden_area_ids],
        "label": window.label,
        "anchor_id": str(window.anchor_id),
    }


def _spelled_slot(slot: EmptySlot) -> JsonObject:
    return {
        "interval": _spelled_span(slot.interval),
        "area_id": str(slot.area_id),
        "reason": slot.reason.value,
    }


def _spelled_span(interval: Interval) -> JsonObject:
    return {"start": interval.start.isoformat(), "end": interval.end.isoformat()}


def _keyed_by_the_day_it_lands_on(spelled: JsonObject) -> None:
    """A habit occurrence keyed the way the frame and a concrete template entry are keyed."""
    for block in spelled["blocks"]:
        if block["binding"]["kind"] == BindingKind.HABIT.value:
            block["binding"]["occurrence_key"] = MONDAY.isoformat()


def _a_binding_kind_by_its_member_name(spelled: JsonObject) -> None:
    """A closed vocabulary written as the Python member's name rather than as its value."""
    for block in spelled["blocks"]:
        block["binding"]["kind"] = BindingKind(block["binding"]["kind"]).name


def _wall_times_with_no_offset(spelled: JsonObject) -> None:
    """Instants written as wall times, which is how a week's own zone map invites reading them."""
    for block in spelled["blocks"]:
        for bound in ("start", "end"):
            block["interval"][bound] = block["interval"][bound].removesuffix("+00:00")


def _only_the_fields_its_own_reader_needs(spelled: JsonObject) -> None:
    """The fields one consumer reads, and none of the rest.

    Every key left out here is a collection the reader defaults to empty, so nothing refuses the
    row: the week it describes is simply not the week that was written.
    """
    for key in ("forbidden_windows", "empty_slots", "adjustments"):
        del spelled[key]


def _the_id_the_block_derives(spelled: JsonObject) -> None:
    """A block's identity, stored beside the binding it is a hash of."""
    for block in spelled["blocks"]:
        block["id"] = "0" * BLOCK_ID_LENGTH


def spelled_around_the_writer(
    choice: Callable[[JsonObject], None],
) -> Callable[[PlanDocument], JsonObject]:
    """A producer that spells the document itself, with one choice made its own way."""

    def produce(document: PlanDocument) -> JsonObject:
        spelled = hand_spelled(document)
        choice(spelled)
        return spelled

    return produce


REFUSED_SPELLINGS = [
    pytest.param(_keyed_by_the_day_it_lands_on, "occurrence key", id="a habit keyed by its day"),
    pytest.param(
        _a_binding_kind_by_its_member_name, "closed vocabulary", id="a vocabulary by member name"
    ),
    pytest.param(_wall_times_with_no_offset, "UTC offset", id="wall times, no offset"),
]


def test_a_week_spelled_by_hand_round_trips_before_a_choice_is_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The control on the parametrization below: every producer there is this spelling with one
    # thing changed, so a spelling that was already illegal would redden the round trip for a
    # reason that has nothing to do with the change. It is also the disproof of the wider claim:
    # a document assembled outside the writer is not refused BECAUSE it was assembled outside it.
    monkeypatch.setitem(globals(), "stored_document", hand_spelled)

    test_a_week_of_every_origin_round_trips_to_the_same_value()


@pytest.mark.parametrize(("choice", "stated"), REFUSED_SPELLINGS)
def test_the_round_trip_reddens_when_a_second_producer_spells_the_document(
    choice: Callable[[JsonObject], None],
    stated: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The round trip above, run against a producer that is not the writer. It has to go red.

    Substituted at the name that round trip calls, so what runs is that assertion rather than a
    copy of it: a copy can drift into asserting something weaker while the original stays green.

    Matched on what each refusal states, because a refusal for another reason would pass a test
    that only asked whether one was raised.
    """
    monkeypatch.setitem(globals(), "stored_document", spelled_around_the_writer(choice))

    with pytest.raises(StoredDocumentCorrupt, match=stated):
        test_a_week_of_every_origin_round_trips_to_the_same_value()


def test_a_producer_spelling_only_what_one_consumer_reads_reddens_it_with_no_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spelling nothing refuses, which is why the comparison is the whole value.

    Every key it leaves out is a collection the reader defaults to empty, so the row is legal and
    the week it describes is missing every concession and gap the one that was written held. A
    comparison over the blocks alone, or over the figures, would hold.
    """
    produce = spelled_around_the_writer(_only_the_fields_its_own_reader_needs)
    document = a_week_of_every_origin()
    monkeypatch.setitem(globals(), "stored_document", produce)

    read = plan_document(produce(document))

    assert (read.forbidden_windows, read.empty_slots, read.adjustments) == ((), (), ())
    assert read.blocks == document.blocks
    assert read != document
    with pytest.raises(AssertionError):
        test_a_week_of_every_origin_round_trips_to_the_same_value()


def test_no_round_trip_can_see_a_producer_that_stores_the_derived_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one choice above that reddens nothing, and the reason the walk below exists.

    The reader takes the keys it knows and ignores the rest, so a stored id reads back as the week
    that was written whatever it holds. Only a reading of that producer's own output sees it, and
    every reading in this file reads the writer's.
    """
    monkeypatch.setitem(
        globals(), "stored_document", spelled_around_the_writer(_the_id_the_block_derives)
    )

    test_a_week_of_every_origin_round_trips_to_the_same_value()

    with pytest.raises(AssertionError):
        test_no_stored_block_carries_an_id()


# --------------------------------------------------------------------------------
# The writer is the only producer
# --------------------------------------------------------------------------------

# The keys a stored document holds, read off the domain's own inventory rather than listed: the
# stored form states every field a document has and no others, which is asserted above.
DOCUMENT_KEYS = frozenset(field.name for field in fields(PlanDocument))

# How many of a document's nine keys a mapping names before it IS one, on top of the week it is
# filed under. Two, because that is the shape of a row built by hand: a week and its blocks, with
# every collection left to default. One key alone is a column most plan-side tables carry, and the
# minute figures alone are also a stored edit context's.
KEYS_THAT_NAME_A_DOCUMENT = 2


def published_key_names(source: str) -> dict[str, str]:
    """Every constant this source publishes whose value is one of a document's keys.

    A producer names a key through a constant as readily as it writes one out, and the constants are
    published in more than one module: the writer holds nine of them and ``plans/derivation.py``
    holds the week's own, which is the key this walk filters on.
    """
    found: dict[str, str] = {}
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        published = statement.value
        if not isinstance(published, ast.Constant) or published.value not in DOCUMENT_KEYS:
            continue
        found.update(
            {target.id: published.value for target in targets if isinstance(target, ast.Name)}
        )
    return found


def package_sources(source_root: Path) -> dict[Path, str]:
    """Every module under ``source_root``, read once. The walk's whole subject set.

    One function owns what the walk reads, so the rule and the controls on it cannot come to
    disagree about which files are covered.
    """
    return {path: path.read_text(encoding="utf-8") for path in sorted(source_root.rglob("*.py"))}


def document_key_names(sources: Iterable[str]) -> dict[str, str]:
    """The key each constant published anywhere in these sources names."""
    found: dict[str, str] = {}
    for source in sources:
        found |= published_key_names(source)
    return found


def _key_named(node: ast.expr | None, names: Mapping[str, str]) -> str | None:
    """The document key this expression names, written out or through a published constant."""
    if isinstance(node, ast.Constant):
        value = node.value
        return value if isinstance(value, str) and value in DOCUMENT_KEYS else None
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.Attribute):
        return names.get(node.attr)
    return None


def _keys_in(nodes: Iterable[ast.expr | None], names: Mapping[str, str]) -> frozenset[str]:
    return frozenset(key for node in nodes if (key := _key_named(node, names)) is not None)


def document_mappings(source: str, names: Mapping[str, str]) -> list[frozenset[str]]:
    """Every mapping in this source that could be filed as a document, and the keys it names.

    Three spellings, because a producer writes whichever reads best where it stands: a display, a
    ``dict`` call, and keys assigned one at a time into a mapping built empty. The assigned form is
    collected per module rather than per mapping, because what carries the keys there is a name.

    Every qualifying mapping names the week, because that is the key the row's own column is
    derived from: ``plans/derivation.py`` refuses a document carrying no ``iso_week`` string, so a
    mapping without one cannot be filed at all.
    """
    tree = ast.parse(source)
    found: list[frozenset[str]] = []
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            found.append(_keys_in(node.keys, names))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dict"
        ):
            found.append(
                frozenset(
                    keyword.arg
                    for keyword in node.keywords
                    if keyword.arg is not None and keyword.arg in DOCUMENT_KEYS
                )
            )
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            assigned |= _keys_in([node.slice], names)
    return [
        keys
        for keys in [*found, frozenset(assigned)]
        if DOCUMENT_ISO_WEEK_KEY in keys and len(keys) >= KEYS_THAT_NAME_A_DOCUMENT
    ]


def modules_that_build_a_stored_document(source_root: Path) -> dict[str, list[str]]:
    """Every module under ``source_root`` that assembles a stored plan document itself.

    Reported with the keys each one names, because that is what makes the answer checkable: a
    mapping caught for some other reason says which keys made it look like a document.
    """
    sources = package_sources(source_root)
    names = document_key_names(sources.values())
    found: dict[str, set[str]] = {}
    for path, source in sources.items():
        for keys in document_mappings(source, names):
            found.setdefault(str(path.relative_to(source_root)), set()).update(keys)
    return {module: sorted(keys) for module, keys in found.items()}


def test_the_writer_is_the_only_module_that_builds_a_stored_document(source_root: Path) -> None:
    """One producer, which is what the round trip above is a claim about.

    An equality rather than an emptiness, so it says three things at once: the producer is where it
    is supposed to be, it names every key a document holds, and no other module of the package
    names the week plus one more. A second producer is the case no round trip catches, because the
    reader ignores what it does not know, and a stored value nothing reads back is a value nothing
    checks.
    """
    writer = str(Path(stored_documents.__file__).resolve().relative_to(source_root))

    assert modules_that_build_a_stored_document(source_root) == {writer: sorted(DOCUMENT_KEYS)}


def test_the_walk_reports_a_second_producer_in_each_spelling(tmp_path: Path) -> None:
    # The control, and it runs the WALK rather than the pattern: a rule whose subject set resolved
    # to no files would pass forever, and a spelling with no control here is a branch of the walk
    # that cannot go red. Written into a directory of its own, so these can never reach the package
    # the rule is stated over.
    #
    # Six producer modules, between them exercising every way the walk recognizes a key or a
    # mapping, plus `spelling.py`, which publishes the names two of them resolve through, and
    # `a_row.py`, the negative: a row naming the week and its own table's columns is not a document.
    #
    # The published names resolve here the way they resolve in the real package, so the derivation
    # is exercised rather than assumed, and one of them carries an annotation because a publisher in
    # the package carries one. The attribute spelling reads that constant, so the arm that reads an
    # annotated publisher has a module against it too.
    #
    # `by_call_with_a_column.py` is the pair to `by_call.py`: a call naming the week, a document
    # field, and a column of its own table. It is the module that notices if the keyword filter
    # goes, which would otherwise report a key no document holds.
    invented = tmp_path / "revisions"
    invented.mkdir()
    (invented / "spelling.py").write_text(
        'ISO_WEEK = "iso_week"\nBLOCKS: str = "blocks"\nEMPTY_SLOTS = "empty_slots"\n',
        encoding="utf-8",
    )
    (invented / "display.py").write_text(
        'stored = {"iso_week": str(week), "blocks": []}\n', encoding="utf-8"
    )
    (invented / "by_constant.py").write_text(
        "stored = {ISO_WEEK: str(week), EMPTY_SLOTS: []}\n", encoding="utf-8"
    )
    (invented / "by_attribute.py").write_text(
        "stored = {spelling.ISO_WEEK: str(week), spelling.BLOCKS: []}\n", encoding="utf-8"
    )
    (invented / "by_call.py").write_text(
        "stored = dict(iso_week=str(week), forbidden_windows=[])\n", encoding="utf-8"
    )
    (invented / "by_call_with_a_column.py").write_text(
        "stored = dict(iso_week=str(week), blocks=[], target_id=target)\n", encoding="utf-8"
    )
    (invented / "assigned.py").write_text(
        'stored = {}\nstored["iso_week"] = str(week)\nstored["adjustments"] = []\n',
        encoding="utf-8",
    )
    (invented / "a_row.py").write_text(
        'row = {"iso_week": str(week), "kind": kind, "target_id": target}\n', encoding="utf-8"
    )

    assert modules_that_build_a_stored_document(tmp_path) == {
        "revisions/assigned.py": ["adjustments", "iso_week"],
        "revisions/by_attribute.py": ["blocks", "iso_week"],
        "revisions/by_call.py": ["forbidden_windows", "iso_week"],
        "revisions/by_call_with_a_column.py": ["blocks", "iso_week"],
        "revisions/by_constant.py": ["empty_slots", "iso_week"],
        "revisions/display.py": ["blocks", "iso_week"],
    }


def test_every_module_that_publishes_a_document_key_name_is_read(source_root: Path) -> None:
    """The key names are published in more than one module, and the walk reads all of them.

    The week key this walk filters on is published by ``plans/derivation.py`` rather than by the
    writer, so a producer keyed by that constant is visible only while every publisher is read.
    """
    names = document_key_names(package_sources(source_root).values())

    assert names["ISO_WEEK"] == DOCUMENT_ISO_WEEK_KEY
    assert names["DOCUMENT_ISO_WEEK_KEY"] == DOCUMENT_ISO_WEEK_KEY
    assert names["BLOCKS"] == "blocks"
    assert names["EMPTY_SLOTS"] == "empty_slots"
    assert names["ZONE_BY_DATE"] == "zone_by_date"


def test_the_walk_reads_the_whole_package_rather_than_one_directory_of_it(
    source_root: Path,
) -> None:
    # The control on the subject set, read off the walk's own reader rather than off a second glob:
    # the writer lives one directory down, so a walk over the top level alone would find no producer
    # at all and the equality above would hold for the wrong reason.
    read = {path.parent for path in package_sources(source_root)}

    assert {source_root, source_root / "plans"} <= read


def test_a_second_producer_inside_the_package_is_reported(
    source_root: Path, tmp_path: Path
) -> None:
    # The mutation, against the real tree rather than an invented one: the package is copied, one
    # module of it gains the mapping a second producer would build, and the walk has to name that
    # module. Copied rather than edited in place, because a rule that has to modify the tree it
    # guards in order to prove it works cannot be run on a whole suite.
    copied = tmp_path / "syncr_api"
    shutil.copytree(source_root, copied)
    adoption = copied / "plans" / "adoption.py"
    adoption.write_text(
        adoption.read_text(encoding="utf-8")
        + "\n\ndef _stored_again(document: object) -> dict[str, object]:\n"
        + '    return {"iso_week": "2026-W07", "blocks": [], "zone_by_date": {}}\n',
        encoding="utf-8",
    )

    assert modules_that_build_a_stored_document(copied)["plans/adoption.py"] == [
        "blocks",
        "iso_week",
        "zone_by_date",
    ]
