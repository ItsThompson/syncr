"""The boundary between a week as a value and a week as a stored row, driven in both directions.

``plan_revisions.document`` is authoritative and nothing in the tree read or wrote one until now,
so the two fixtures that stood in for this path were both malformed: a habit keyed by a date, which
``BindingRef`` refuses, and a 32-character block id where the derivation produces 64. They are what
a reader written from the fixtures would have produced, which is why the round trip is asserted
over a week holding one block of each of the seven origins rather than over one convenient block.

Four groups.

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
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

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
from syncr_domain.identity import BindingKind, BindingRef, Origin, TransitLeg, binding_kind_of
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
    ReasonRecord,
)
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonObject
    from syncr_domain.intervals import Interval

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

    Seven origins in one document is the shape 1222 asks the round trip to cover, and it is also
    the shape that catches a reader keyed on one kind: each of the seven is keyed differently.
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
            Floor(area_id=FITNESS, floor_minutes=180, placed=90, of=180),
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


def test_the_two_vocabularies_a_bound_source_spans_are_disjoint() -> None:
    """One stored word has to name exactly one source, and nothing else makes that decidable."""
    derivations = {member.value for member in DerivationSource}
    bindings = {member.value for member in BindingSource}

    assert not derivations & bindings


@pytest.mark.parametrize(
    "source",
    [*DerivationSource, *BindingSource],
    ids=[member.value for member in (*DerivationSource, *BindingSource)],
)
def test_every_bound_source_round_trips_to_its_own_vocabulary(source: Any) -> None:
    document = a_document(
        blocks=(a_block(Origin.HABIT, reason=ReasonRecord((Bound(source, "Gym · Legs"),))),)
    )

    read = plan_document(stored_document(document))
    (clause,) = read.blocks[0].reason.clauses

    assert isinstance(clause, Bound)
    assert clause.source is source
