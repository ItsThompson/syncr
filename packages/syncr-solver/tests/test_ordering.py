"""The order each of a week's collections is held in, and the property every key holds.

Determinism rather than legality. A partial key fails silently, because a stable sort returns the
arrival order when the key cannot separate two unequal values, so each test below builds one week
TWICE with the pair permuted and compares. A single build can never see it.
"""

from __future__ import annotations

import dataclasses
from uuid import UUID

import pytest

from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_solver.ordering import WINDOW_ORDER_FIELDS
from syncr_solver.state import PartialPlan
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    a_recovery_window,
    an_area_budget,
    an_off_plan_period,
    between,
    inputs,
)

AN_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000bb")
ANOTHER_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000cc")


def test_an_off_plan_period_is_ordered_by_every_field_it_carries() -> None:
    # The span alone is total over a legal input, because two periods of one tenant never cover a
    # common instant. So the pair below is not one a tenant can hold, and the key reads the rest of
    # the value anyway: the order a document is held in does not rest on an invariant checked in
    # another module, and a stable sort on a partial key would return the arrival order instead.
    span = between(1, 2)
    kept = an_off_plan_period(interval=span, keep_frame=True)
    dropped = an_off_plan_period(interval=span)

    forwards = PartialPlan.of(inputs(off_plan=(kept, dropped))).off_plan
    backwards = PartialPlan.of(inputs(off_plan=(dropped, kept))).off_plan

    assert forwards == backwards == (dropped, kept)


def test_two_off_plan_periods_of_one_tenant_are_held_in_span_order() -> None:
    early = an_off_plan_period(interval=between(1, 2))
    late = an_off_plan_period(interval=between(3, 4), keep_frame=True)

    forwards = PartialPlan.of(inputs(off_plan=(early, late))).off_plan
    backwards = PartialPlan.of(inputs(off_plan=(late, early))).off_plan

    assert forwards == backwards == (early, late)


def test_two_area_budgets_are_ordered_by_the_identity_they_answer_for() -> None:
    fitness = an_area_budget(area_id=FITNESS, name="Fitness")
    career = an_area_budget(area_id=CAREER, name="Career")

    forwards = PartialPlan.of(inputs(areas=(fitness, career))).areas
    backwards = PartialPlan.of(inputs(areas=(career, fitness))).areas

    assert forwards == backwards == (fitness, career)


# The one key whose trailing field is not an identity. Two windows differing in exactly one field,
# per field a window carries: a commitment casts up to four windows, so every one of these pairs is
# a pair one anchor can produce.
WINDOWS_DIFFERING_IN_ONE_FIELD: list[tuple[str, ForbiddenWindow, ForbiddenWindow]] = [
    (
        "interval",
        a_recovery_window(interval=between(11, 12), anchor_id=AN_ANCHOR_ID),
        a_recovery_window(interval=between(11, 12.5), anchor_id=AN_ANCHOR_ID),
    ),
    (
        "kind",
        a_recovery_window(anchor_id=AN_ANCHOR_ID),
        ForbiddenWindow(
            between(11, 12),
            ForbiddenKind.PREP_UNATTRIBUTED,
            ForbiddenScope.ALL,
            (),
            "recovery · Kontron Placement Interview",
            AN_ANCHOR_ID,
        ),
    ),
    (
        "label",
        a_recovery_window(anchor_id=AN_ANCHOR_ID, label="recovery · Lecture"),
        a_recovery_window(anchor_id=AN_ANCHOR_ID, label="recovery · Seminar"),
    ),
    (
        "anchor_id",
        a_recovery_window(anchor_id=AN_ANCHOR_ID),
        a_recovery_window(anchor_id=ANOTHER_ANCHOR_ID),
    ),
    (
        "scope",
        a_recovery_window(anchor_id=AN_ANCHOR_ID),
        a_recovery_window(
            anchor_id=AN_ANCHOR_ID,
            scope=ForbiddenScope.AREAS,
            forbidden_area_ids=(FITNESS,),
        ),
    ),
    (
        "forbidden_area_ids",
        a_recovery_window(
            anchor_id=AN_ANCHOR_ID,
            scope=ForbiddenScope.AREAS,
            forbidden_area_ids=(FITNESS,),
        ),
        a_recovery_window(
            anchor_id=AN_ANCHOR_ID,
            scope=ForbiddenScope.AREAS,
            forbidden_area_ids=(CAREER,),
        ),
    ),
]


def test_the_window_order_reads_every_field_a_window_carries() -> None:
    # Bounded by the inventory rather than by the fields anyone thought of: the anchor is not a
    # per-window identity, because one commitment casts up to four windows, so the order has to read
    # the whole value. A seventh field on a window fails here until this key reads it.
    assert set(WINDOW_ORDER_FIELDS) == {field.name for field in dataclasses.fields(ForbiddenWindow)}


@pytest.mark.parametrize(
    ("field", "one", "other"),
    [(case[0], case[1], case[2]) for case in WINDOWS_DIFFERING_IN_ONE_FIELD],
    ids=[case[0] for case in WINDOWS_DIFFERING_IN_ONE_FIELD],
)
def test_two_windows_one_anchor_cast_are_ordered_by_the_field_they_differ_in(
    field: str, one: ForbiddenWindow, other: ForbiddenWindow
) -> None:
    # Ordered by input arrival, a document's windows would depend on which of a pair the producer
    # listed first while describing the same week, and the byte-identity property would be false.
    forwards = PartialPlan.of(inputs(forbidden_windows=(one, other))).forbidden_windows
    backwards = PartialPlan.of(inputs(forbidden_windows=(other, one))).forbidden_windows

    assert one != other, field
    assert forwards == backwards
