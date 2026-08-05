"""A candidate concession's round trip: onto an operation as JSON, and back as the value folded.

The channel exists because the assembler takes the candidate as an ARGUMENT, which is what keeps
a tradeoff request from persisting anything, and the operation is the only object that crosses from
the request to the worker. So the shape is written by one component and read by another, and the
failure this suite exists against is the two disagreeing: a concession the user asked for arriving
at the worker as a different one, or as none.

The reductions are the interesting part in both directions. Writing spells each date the way the
stored column and the frame occurrence spell it, so the fold pairs them without a second derivation.
Reading is tolerant of a key this week cannot honour and reports what it dropped, because a document
already written has to be readable; refusing one is the write's job, and the table does it.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syncr_api.plans.candidates import (
    ADJUSTMENT_ID,
    DELTA_MINUTES,
    KIND,
    REDUCTIONS,
    TARGET_ID,
    as_document,
    from_document,
    reductions_of,
)
from syncr_api.plans.errors import AdjustmentRejected
from syncr_common.logging import configure_logging
from syncr_domain.fixtures import elastic_sleep
from syncr_domain.plan import AdjustmentKind
from syncr_solver.inputs import WeekAdjustment

if TYPE_CHECKING:
    from collections.abc import Iterator

WEEK_DATES = list(elastic_sleep.WEEK.dates())


def a_candidate(**overrides: Any) -> WeekAdjustment:
    stated: dict[str, Any] = {
        "adjustment_id": uuid4(),
        "kind": AdjustmentKind.BREACH_FLOOR,
        "target_id": uuid4(),
        "delta_minutes": 80,
    }
    stated.update(overrides)
    return WeekAdjustment(**stated)


@pytest.mark.parametrize("kind", list(AdjustmentKind))
def test_a_candidate_of_any_kind_survives_the_trip_to_the_worker(kind: AdjustmentKind) -> None:
    # Bounded by the vocabulary rather than by a list here, so a fifth kind cannot arrive with a
    # shape nobody can read back.
    reductions = elastic_sleep.REDUCTIONS if kind is AdjustmentKind.REDUCE_ROUTINE else {}
    candidate = a_candidate(kind=kind, reductions=reductions)

    read = from_document(as_document(candidate), dates=WEEK_DATES)

    assert read == candidate


def test_the_document_spells_a_date_the_way_the_stored_column_does() -> None:
    # One spelling across the candidate, the stored row, and the frame occurrence key: the fold
    # pairs a reduction with an occurrence by that key, so a second spelling pairs with nothing.
    candidate = a_candidate(kind=AdjustmentKind.REDUCE_ROUTINE, reductions=elastic_sleep.REDUCTIONS)

    document = as_document(candidate)

    assert document[REDUCTIONS] == {
        "2026-02-10": 20,
        "2026-02-11": 20,
        "2026-02-12": 20,
    }
    assert document[KIND] == AdjustmentKind.REDUCE_ROUTINE.value
    assert document[TARGET_ID] == str(candidate.target_id)
    assert document[ADJUSTMENT_ID] == str(candidate.adjustment_id)
    assert document[DELTA_MINUTES] == candidate.delta_minutes


@pytest.mark.parametrize(
    ("document", "refused"),
    [
        ({KIND: "cancel_the_week"}, "not one of the four"),
        ({KIND: None}, "not one of the four"),
        ({KIND: AdjustmentKind.DROP_ITEM.value, TARGET_ID: "not-an-identifier"}, "identifier"),
        ({KIND: AdjustmentKind.DROP_ITEM.value, ADJUSTMENT_ID: "not-an-identifier"}, "identifier"),
        (
            {KIND: AdjustmentKind.BREACH_FLOOR.value, DELTA_MINUTES: "eighty"},
            "not a count of minutes",
        ),
    ],
)
def test_a_document_that_describes_no_concession_is_refused(
    document: dict[str, Any], refused: str
) -> None:
    # The solve fails and says why. A document read past its own defects would solve the week
    # WITHOUT the concession the user asked for and land a proposal that looks like it ignored them,
    # which is the one outcome the request path exists to prevent.
    stated = {ADJUSTMENT_ID: str(uuid4()), TARGET_ID: str(uuid4()), **document}

    with pytest.raises(AdjustmentRejected, match=refused):
        from_document(stated, dates=WEEK_DATES)


def test_a_missing_reductions_key_reads_as_no_reductions_rather_than_a_refusal() -> None:
    # Three of the four kinds carry none, so an absent mapping is the ordinary case.
    document = {
        ADJUSTMENT_ID: str(uuid4()),
        KIND: AdjustmentKind.DROP_ITEM.value,
        TARGET_ID: str(uuid4()),
    }

    assert from_document(document, dates=WEEK_DATES).reductions == {}


@pytest.fixture
def captured_log() -> Iterator[io.StringIO]:
    """Render to a captured stream, then hand the configuration back.

    Logging configuration is process-global, and ``conftest.py`` fails the test that leaves it
    changed, so the restore is part of the fixture rather than an afterthought.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


def test_a_reduction_this_week_cannot_honour_is_dropped_and_reported(
    captured_log: io.StringIO,
) -> None:
    # Tolerant on the read, and loud: an entry that pairs with no occurrence would otherwise leave
    # the concession claiming to have been honoured while changing nothing.
    read = reductions_of(
        {"not-a-date": 30, "2030-01-01": 60, WEEK_DATES[1].isoformat(): 20}, dates=WEEK_DATES
    )

    assert read == {WEEK_DATES[1]: 20}
    lines = captured_log.getvalue()
    assert "plans.adjustment.unreadable_reduction" in lines
    assert "plans.adjustment.reduction_outside_the_week" in lines
