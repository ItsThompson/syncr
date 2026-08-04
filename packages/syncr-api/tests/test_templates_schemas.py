"""The day-shape wire contract, asserted without a server.

Three properties of these shapes are load-bearing and none of them is visible in a response body.

The week-pattern shape names its fields for the weekdays, which is what lets the mapping be read
back without seven statements of the same thing. The two entry requests are the pairing rule, so
each has to be missing exactly what the other requires. And nothing in this package's contract may
carry a cadence or say anything about a pin: recurrence lives on a habit, and a template entry is
fixed by derivation rather than pinned, so a client has nothing to render a glyph from.
"""

from __future__ import annotations

from datetime import time
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from syncr_api.templates.entry_schemas import (
    ConcreteEntryRequest,
    EntryPatchRequest,
    SlotEntryRequest,
    TemplateEntryResponse,
)
from syncr_api.templates.schemas import (
    DayTypeCreateRequest,
    TemplateCreateRequest,
    TemplatePatchRequest,
    WeekPatternRequest,
    WeekPatternResponse,
)
from syncr_domain.templates import BindingTarget, TemplateEntryKind, WeekPattern
from syncr_domain.weeks import Weekday

REQUESTS: tuple[type[BaseModel], ...] = (
    DayTypeCreateRequest,
    TemplateCreateRequest,
    TemplatePatchRequest,
    ConcreteEntryRequest,
    SlotEntryRequest,
    EntryPatchRequest,
    WeekPatternRequest,
)


def a_mapping() -> dict[str, str]:
    return {weekday.value: str(uuid4()) for weekday in Weekday}


def test_the_pattern_shape_names_every_weekday() -> None:
    # The mapping is read back by field name, so the field names and the weekday vocabulary have
    # to be the same seven words. Without this the reflection would fail at runtime only.
    assert set(WeekPatternRequest.model_fields) == {weekday.value for weekday in Weekday}


def test_a_pattern_round_trips_through_the_domain_shape() -> None:
    sent = a_mapping()

    pattern = WeekPattern(WeekPatternRequest.model_validate(sent).mapping())

    assert WeekPatternResponse.of(pattern.mapping).model_dump(mode="json") == sent


@pytest.mark.parametrize("left_out", [weekday.value for weekday in Weekday])
def test_a_pattern_request_refuses_a_partial_mapping(left_out: str) -> None:
    sent = a_mapping()
    del sent[left_out]

    with pytest.raises(ValidationError) as refused:
        WeekPatternRequest.model_validate(sent)

    assert [error["loc"] for error in refused.value.errors()] == [(left_out,)]


def test_a_concrete_request_cannot_omit_its_binding() -> None:
    with pytest.raises(ValidationError):
        ConcreteEntryRequest.model_validate(
            {"kind": "concrete", "targetTime": "07:00:00", "durationMinutes": 15}
        )


def test_a_slot_request_has_nowhere_to_put_a_binding() -> None:
    with pytest.raises(ValidationError):
        SlotEntryRequest.model_validate(
            {
                "kind": "slot",
                "targetTime": "07:00:00",
                "durationMinutes": 15,
                "areaId": str(uuid4()),
                "bindingRef": str(uuid4()),
            }
        )


def test_each_request_builds_the_declaration_its_kind_holds() -> None:
    binding = uuid4()
    area = uuid4()

    concrete = ConcreteEntryRequest.model_validate(
        {
            "kind": "concrete",
            "targetTime": "07:00:00",
            "durationMinutes": 45,
            "bindingTarget": "habit",
            "bindingRef": str(binding),
        }
    ).declaration()
    slot = SlotEntryRequest.model_validate(
        {
            "kind": "slot",
            "targetTime": "18:00:00",
            "durationMinutes": 60,
            "areaId": str(area),
        }
    ).declaration()

    assert concrete.content().kind == TemplateEntryKind.CONCRETE
    assert concrete.content().binding_target == BindingTarget.HABIT
    assert concrete.content().binding_ref == binding
    assert concrete.span.target_time == time(7, 0)
    assert slot.content().kind == TemplateEntryKind.SLOT
    assert slot.content().area_id == area
    assert slot.content().binding_ref is None


@pytest.mark.parametrize("request_shape", REQUESTS)
def test_no_request_shape_accepts_a_cadence(request_shape: type[BaseModel]) -> None:
    # A period on a template would be the fourth concept the three this package ships exist to
    # avoid, so every request forbids an unknown field rather than dropping one.
    assert not [
        field
        for field in request_shape.model_fields
        if any(word in field.lower() for word in ("cadence", "period", "repeat", "frequency"))
    ]
    assert request_shape.model_config.get("extra") == "forbid"


def test_no_shape_says_anything_about_a_pin() -> None:
    # A template entry is fixed by derivation: no Pin row, no glyph, and not a training label.
    shapes: tuple[type[BaseModel], ...] = (*REQUESTS, TemplateEntryResponse)

    for shape in shapes:
        assert not [field for field in shape.model_fields if "pin" in field.lower()]
