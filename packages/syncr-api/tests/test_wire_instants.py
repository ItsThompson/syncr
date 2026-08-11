"""One reading of an instant, asserted over the whole wire surface rather than over one route.

Three claims, each stated once here and checked against every field the walk finds:

* a value with no UTC offset is refused, whether it is a wall clock or a bare date
* an aware value renders its offset back
* the reading is reached through the ONE shared type, so a new field cannot be laxer than
  the rest by being spelled differently

The population comes from ``tests/wire_census.py``, which discovers it. What is asserted here is
therefore a property of whatever surface exists when the suite runs, and the landmarks below are
what keeps that honest: a walk narrowed to one module, or to one of its two sources, drops a
shape this file names and goes red rather than passing over less.

The document is crossed against the walk as well. It is a different reading of the same claim,
taken from what a client is generated from, and it can see a field in a shape the walk's two
sources both missed.

What this file cannot see is an instant that reaches a client without passing through a field:
a handler that renders its own mapping through a bare ``Response`` renders whatever it holds.
Every route in this application answers with a declared model or with no body at all, and the
event stream serialises the same models, so there is no such site today; there is also no check
here that would notice a new one.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from syncr_api.core.app_factory import create_app
from syncr_api.core.schemas import WireInstant
from syncr_api.core.settings import EnvSettings, build_service_settings
from tests.wire_census import (
    InstantField,
    InstantParameter,
    carries_an_instant,
    instant_fields,
    instant_parameters,
    models_extending_the_wire_base,
    models_the_contract_is_generated_from,
    names_the_shared_instant,
    qualified,
    takes_the_shared_reading,
    wire_models,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

# The three readings that name no instant: a wall clock as text, a bare date, and a naive value
# handed in as Python rather than parsed from a request.
NAIVE_TEXT: Final = "2026-03-08T09:00"
BARE_DATE: Final = "2026-03-08"
NAIVE_VALUE: Final = datetime(2026, 3, 8, 9, 0)  # noqa: DTZ001 - the refusal is the point

# Two aware values, because one of them is UTC and pydantic renders that as `Z`: a type that
# rendered only `Z` correctly would pass on the first and fail a caller in Kathmandu.
UTC_VALUE: Final = datetime(2026, 3, 8, 9, 0, tzinfo=UTC)
OFFSET_VALUE: Final = datetime(2026, 3, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kathmandu"))

# What pydantic calls the refusal, so a test asserts the reason rather than only the failure.
REFUSED: Final = "timezone_aware"

AN_OFFSET: Final = re.compile(r"(Z|[+-]\d{2}:\d{2})$")

# What the document calls an instant, and the one component that may declare it.
DATE_TIME: Final = "date-time"
SHARED_COMPONENT: Final = "WireInstant"

# The shapes this walk must reach. Named so that narrowing the walk is a red suite rather than a
# quieter one: the three a task's deadline is declared on, the three a project's is, the shared
# span both of whose bounds are instants, and an off-plan period's own pair.
LANDMARKS: Final = frozenset(
    {
        "syncr_api.tasks.schemas.TaskCreateRequest.deadline",
        "syncr_api.tasks.schemas.TaskPatchRequest.deadline",
        "syncr_api.tasks.schemas.TaskResponse.deadline",
        "syncr_api.areas.schemas.ProjectCreateRequest.deadline",
        "syncr_api.areas.schemas.ProjectPatchRequest.deadline",
        "syncr_api.areas.schemas.ProjectResponse.deadline",
        "syncr_api.core.schemas.WireSpan.start",
        "syncr_api.core.schemas.WireSpan.end",
        "syncr_api.offplan.schemas.OffPlanCreateRequest.start",
        "syncr_api.offplan.schemas.OffPlanCreateRequest.end",
    }
)

# What each source of the walk reaches that the other cannot. The learning routes declare a
# camel-casing base of their own, so only the document's own field list reaches their instants. The
# base walk's own contribution is a shape no route mounts, which today carries no instant at all:
# it is there so a field written before its route is bounded too.
ONLY_THE_DOCUMENT_REACHES = "syncr_api.learned.schemas.LearnedResponse.fitted_at"
MOUNTED_BY_NO_ROUTE = "syncr_api.pins.schemas.PinReleased"

# An application built at COLLECTION time, because each field is its own case and pytest needs the
# population before a fixture has run. Built the way the suite's own fixture builds one, from
# defaults alone, so a developer's environment cannot change what is collected.
_COLLECTED = create_app(
    build_service_settings(service="syncr-api-census", env=EnvSettings(_env_file=None))
)
INSTANT_FIELDS: Final = instant_fields(wire_models(_COLLECTED))
INSTANT_PARAMETERS: Final = instant_parameters(_COLLECTED)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One case per field and per parameter, named after the field it is about."""
    if "field" in metafunc.fixturenames:
        metafunc.parametrize("field", INSTANT_FIELDS, ids=[one.where for one in INSTANT_FIELDS])
    if "parameter" in metafunc.fixturenames:
        metafunc.parametrize(
            "parameter", INSTANT_PARAMETERS, ids=[one.where for one in INSTANT_PARAMETERS]
        )


def where(fields: tuple[InstantField, ...]) -> set[str]:
    return {field.where for field in fields}


def _refusal_of(error: ValidationError) -> set[str]:
    return {one["type"] for one in error.errors()}


class TestTheWalkReachesTheWholeSurface:
    """The census's own reach, before anything is asserted through it."""

    def test_it_reaches_every_shape_named_here(self, app: FastAPI) -> None:
        assert where(instant_fields(wire_models(app))) >= LANDMARKS

    def test_it_reaches_more_than_the_shapes_named_here(self, app: FastAPI) -> None:
        # A walk trimmed to its own landmarks would satisfy the test above and assert nothing
        # about the surface, which is the failure this file exists to avoid.
        assert where(instant_fields(wire_models(app))) - LANDMARKS

    def test_the_document_walk_reaches_an_instant_the_base_walk_cannot(self, app: FastAPI) -> None:
        # The document's own field list is load-bearing rather than a second opinion: a shape that
        # declares its casing itself is on the wire and is not a subclass of the wire base.
        from_the_base = where(instant_fields(models_extending_the_wire_base()))
        from_the_document = where(instant_fields(models_the_contract_is_generated_from(app)))

        assert ONLY_THE_DOCUMENT_REACHES in from_the_document - from_the_base

    def test_the_base_walk_reaches_a_shape_no_route_mounts(self, app: FastAPI) -> None:
        # The other half of the union, and what it buys is reach rather than a field: a wire shape
        # exists before the route that answers with it. It contributes no instant today, so this
        # asserts the reach itself rather than a field the document walk would also have found.
        mounted = {qualified(model) for model in models_the_contract_is_generated_from(app)}
        declared = {qualified(model) for model in models_extending_the_wire_base()}

        assert MOUNTED_BY_NO_ROUTE in declared - mounted

    def test_the_predicate_reads_the_lax_spelling_as_an_instant_too(self) -> None:
        # What lets one walk find both the fields to enforce over and the fields that have not
        # adopted the shared spelling. A predicate blind to `datetime` would report a surface
        # that had already drifted as clean.
        assert carries_an_instant(datetime)
        assert carries_an_instant(datetime | None)
        assert carries_an_instant(WireInstant)
        assert not carries_an_instant(str)
        assert not names_the_shared_instant(datetime | None)


class TestEveryInstantFieldRefusesAValueThatNamesNoInstant:
    @pytest.mark.parametrize(
        "naive", [NAIVE_TEXT, BARE_DATE, NAIVE_VALUE], ids=["wall", "date", "value"]
    )
    def test_it_is_refused_with_the_stated_reason(self, field: InstantField, naive: object) -> None:
        with pytest.raises(ValidationError) as refusal:
            field.adapter.validate_python(naive)

        assert REFUSED in _refusal_of(refusal.value), field.where


class TestEveryInstantFieldRendersItsOffset:
    @pytest.mark.parametrize("aware", [UTC_VALUE, OFFSET_VALUE], ids=["utc", "kathmandu"])
    def test_the_rendered_value_carries_one(self, field: InstantField, aware: datetime) -> None:
        rendered = field.adapter.dump_python(aware, mode="json")

        assert isinstance(rendered, str)
        assert AN_OFFSET.search(rendered), f"{field.where} rendered {rendered!r}"


class TestEveryInstantIsSpelledOnce:
    def test_the_field_reaches_its_reading_through_the_shared_type(
        self, field: InstantField
    ) -> None:
        assert names_the_shared_instant(field.annotation), (
            f"{field.where} declares an instant of its own. The one in core/schemas.py is the "
            "reading every field on this wire takes."
        )

    def test_the_document_declares_the_instant_in_one_place(self, app: FastAPI) -> None:
        # The document is what a client is generated from, so this crosses the claim against a
        # surface the walk does not read: an inline instant in a schema is a field whose reading
        # was declared beside it.
        #
        # A PARAMETER is the exception, and it is the framework's rather than a choice: an alias is
        # resolved while a parameter's field is built, so its schema is rendered inline where a
        # body field's is a reference. Which parameters those are is crossed against the walk, so a
        # new inline instant has to be a parameter the walk found.
        declaring = _paths_declaring_an_instant(app.openapi())
        in_a_schema = {one for one in declaring if one[:2] == ("components", "schemas")}
        in_a_parameter = {
            one for one in declaring if one[-1] == "schema" and one[-3] == "parameters"
        }

        assert in_a_schema == {("components", "schemas", SHARED_COMPONENT)}
        assert declaring == in_a_schema | in_a_parameter
        assert len(in_a_parameter) == len(INSTANT_PARAMETERS)


class TestEveryInstantParameterIsTheSameReading:
    """A parameter is on the wire as much as a body field, and takes the same type."""

    def test_the_walk_reaches_one(self) -> None:
        assert INSTANT_PARAMETERS

    @pytest.mark.parametrize("naive", [NAIVE_TEXT, BARE_DATE], ids=["wall", "date"])
    def test_a_value_that_names_no_instant_is_refused(
        self, parameter: InstantParameter, naive: str
    ) -> None:
        with pytest.raises(ValidationError) as refusal:
            parameter.adapter.validate_python(naive)

        assert REFUSED in _refusal_of(refusal.value), parameter.where

    def test_it_is_spelled_with_the_shared_type(self, parameter: InstantParameter) -> None:
        assert takes_the_shared_reading(parameter.annotation), parameter.where


def _paths_declaring_an_instant(document: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Every place in ``document`` that declares an instant inline, by its path."""
    found: set[tuple[str, ...]] = set()
    if isinstance(document, dict):
        if document.get("format") == DATE_TIME:
            return {path}
        for key, value in document.items():
            found |= _paths_declaring_an_instant(value, (*path, str(key)))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found |= _paths_declaring_an_instant(value, (*path, str(index)))
    return found
