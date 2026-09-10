"""Resolved content and immovable facts carried by ``SolveInputs``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from syncr_domain.identity import date_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.plan import PlanError
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import IsoWeek
from syncr_solver import inputs
from syncr_solver.resolved_content import (
    Anchor,
    EntryBinding,
    FrameEntry,
    HabitOccurrence,
    MaterializedEntry,
    Pin,
    ResolvedPreference,
    ShadowBlock,
    WeekAdjustment,
)

RESOLVED_MEMBER_TYPES = (
    FrameEntry,
    EntryBinding,
    MaterializedEntry,
    HabitOccurrence,
    ResolvedPreference,
    Anchor,
    ShadowBlock,
    Pin,
    WeekAdjustment,
)

WEEK = IsoWeek(2026, 7)
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)


def test_resolved_members_live_here_and_remain_available_from_inputs() -> None:
    for member_type in RESOLVED_MEMBER_TYPES:
        assert member_type.__module__ == "syncr_solver.resolved_content"
        assert getattr(inputs, member_type.__name__) is member_type


def an_entry(kind: TemplateEntryKind, **overrides: object) -> MaterializedEntry:
    stated: dict[str, object] = {
        "entry_id": uuid4(),
        "occurrence_key": date_occurrence_key(WEEK.monday()),
        "kind": kind,
        "interval": Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(minutes=15)),
        "flex_band_minutes": 0,
        "area_id": uuid4(),
        "day_type_name": "Weekday",
    }
    stated.update(overrides)
    return MaterializedEntry(**stated)  # type: ignore[arg-type]


def test_a_concrete_entry_carries_the_content_it_names_and_the_name_of_it() -> None:
    binding = EntryBinding(target=BindingTarget.HABIT, entity_id=uuid4())

    entry = an_entry(TemplateEntryKind.CONCRETE, binding=binding, title="Shower")

    assert (entry.binding, entry.title) == (binding, "Shower")


def test_a_slot_carries_neither_a_binding_nor_a_name_because_nothing_is_chosen_yet() -> None:
    entry = an_entry(TemplateEntryKind.SLOT)

    assert (entry.binding, entry.title) == (None, None)


@pytest.mark.parametrize(
    ("kind", "overrides"),
    [
        (TemplateEntryKind.CONCRETE, {"title": "Shower"}),
        (
            TemplateEntryKind.CONCRETE,
            {"binding": EntryBinding(target=BindingTarget.HABIT, entity_id=uuid4())},
        ),
        (TemplateEntryKind.CONCRETE, {"binding": None, "title": ""}),
        (
            TemplateEntryKind.SLOT,
            {"binding": EntryBinding(target=BindingTarget.ROUTINE, entity_id=uuid4())},
        ),
        (TemplateEntryKind.SLOT, {"title": "Shower"}),
    ],
)
def test_half_a_content_statement_is_refused_whichever_half_it_is(
    kind: TemplateEntryKind, overrides: dict[str, object]
) -> None:
    with pytest.raises(PlanError):
        an_entry(kind, **overrides)


def test_an_entry_of_either_kind_carries_the_area_its_minutes_are_charged_to() -> None:
    with pytest.raises(TypeError):
        MaterializedEntry(  # type: ignore[call-arg]
            entry_id=uuid4(),
            occurrence_key=date_occurrence_key(WEEK.monday()),
            kind=TemplateEntryKind.SLOT,
            interval=Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(minutes=15)),
            flex_band_minutes=0,
        )
