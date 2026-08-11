"""The operation body's completeness: every declared key reaches a client, on the wire.

The optionality rule in ``test_week_view_composition.py`` reads the model. It asks whether pydantic
calls a field required, which is what decides the ``required`` list in the generated document and
therefore whether the generated TypeScript spells a key ``field?:``. It cannot see a body.

That leaves a gap this file closes. A declared-required key can still be absent from what a client
reads, because presence is decided twice: once by the model, and again by whatever serializes it.
Two settings drop a null after the model has called the field required, and each has its own tier:

- ``exclude_none`` inside the event channel's dumper, which every SSE frame goes through;
- ``response_model_exclude_none`` on a route, which every HTTP response goes through.

Either one would leave both generated artifacts declaring the key while no client ever receives it,
and after the operation shape's keys became required, a client narrowing only ``null`` has no branch
for the absence. So the two tiers are asserted here, over a record whose every nullable member is
null, which is the only record that can tell presence from absence.

Asserted through the shipped path rather than by re-spelling it: ``operation_event`` is what the
event channel publishes, so the dump under test is the dump a client reads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI

from syncr_api.core.app_factory import create_app
from syncr_api.events.envelopes import operation_event
from syncr_api.solving.config import PENDING, SOLVE
from syncr_api.solving.records import OperationRecord
from syncr_api.solving.schemas import OperationResponse, OperationTarget
from syncr_domain.weeks import IsoWeek
from tests.boundaries import serialization_views

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings
    from tests.boundaries import SerializationView

# The keys a client is entitled to find, in their wire spelling: the eight that carried a default,
# minus the two on the nested target, which are asserted inside it.
NULLABLE_KEYS = frozenset(
    {"inputVersion", "startedAt", "finishedAt", "resultRevisionId", "supersededBy", "error"}
)
TARGET_NULLABLE_KEYS = frozenset({"isoWeek", "sourceId"})


def a_record_with_every_nullable_member_null() -> OperationRecord:
    """A pending solve, the state in which every nullable member of the wire shape is null.

    A record with values in those columns cannot distinguish a serializer that drops nulls from one
    that does not, so this is the only shape the rule below can be stated over.
    """
    return OperationRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        kind=SOLVE,
        status=PENDING,
        iso_week=IsoWeek(2026, 7),
        source_id=None,
        input_version=None,
        candidate_adjustment=None,
        scheduled_for=datetime(2026, 2, 9, 9, tzinfo=UTC),
        started_at=None,
        finished_at=None,
        result_revision_id=None,
        superseded_by=None,
        attempt=1,
        error_code=None,
        error_message=None,
    )


def serializing_routes(app: FastAPI) -> list[SerializationView]:
    """Every route that renders a response model, through the walk the boundary tests share.

    An application's own ``routes`` list holds included routers rather than the routes they
    contribute: measured at this commit, 27 of the 31 entries are includes and not one of the four
    remaining exposes a serialization setting. A census that filtered that list for the framework's
    route class would compare an empty set against an empty set and pass forever.
    """
    return serialization_views(app)


def test_an_operation_frame_carries_every_nullable_key_rather_than_omitting_the_null() -> None:
    """The event tier. A dropped null here is invisible to the model and to both artifacts."""
    data = operation_event(a_record_with_every_nullable_member_null()).data

    assert set(data) >= NULLABLE_KEYS, sorted(NULLABLE_KEYS - set(data))
    assert {key: data[key] for key in NULLABLE_KEYS} == dict.fromkeys(NULLABLE_KEYS)
    target = data["target"]
    assert isinstance(target, dict)
    assert set(target) >= TARGET_NULLABLE_KEYS, sorted(TARGET_NULLABLE_KEYS - set(target))
    assert target["sourceId"] is None


def test_the_declared_keys_and_the_serialized_keys_are_the_same_set() -> None:
    """The crossing: what the document promises against what one body actually holds.

    Derived from the model's own field set rather than from a list, so a member added to the shape
    is covered without this test being extended.
    """
    declared = {field.alias or name for name, field in OperationResponse.model_fields.items()}

    data = operation_event(a_record_with_every_nullable_member_null()).data

    assert set(data) == declared


def test_no_route_answers_a_body_with_its_nulls_dropped(settings: ServiceSettings) -> None:
    """The HTTP tier, over every route the application declares rather than the operation ones.

    Stated for the whole app because the setting is per route and nothing about it is specific to
    this shape: a route that drops nulls breaks every client narrowing a nullable key it declares.
    """
    dropping = {
        view.path
        for view in serializing_routes(create_app(settings))
        if view.excludes_none or view.excludes_unset
    }

    assert dropping == set()


def test_the_route_census_reports_a_route_that_drops_its_nulls() -> None:
    """The control, and it is stated over an INCLUDED router rather than a bare app.

    The census reads a walk that expands includes, and the reason it has to is that this
    application contributes every one of its routes that way. A control that registered the route
    directly on the app would pass against a census blind to exactly the routes that matter.
    """
    router = APIRouter()

    @router.get("/drops", response_model=OperationTarget, response_model_exclude_none=True)
    async def _drops() -> OperationTarget:  # pragma: no cover - never called
        return OperationTarget(iso_week=None, source_id=None)

    app = FastAPI()
    app.include_router(router)

    dropping = [view for view in serializing_routes(app) if view.excludes_none]

    assert [view.path for view in dropping] == ["/drops"]


def test_the_frame_rule_is_stated_over_a_record_that_can_fail_it() -> None:
    """The other control: the record really does hold a null in every member the rule names."""
    rendered = OperationResponse.of(a_record_with_every_nullable_member_null())

    for name in ("input_version", "started_at", "finished_at", "result_revision_id", "error"):
        assert getattr(rendered, name) is None, name
    assert rendered.superseded_by is None
    assert rendered.target.source_id is None


@pytest.mark.parametrize("key", sorted(NULLABLE_KEYS))
def test_every_named_key_is_a_member_of_the_shape_it_is_named_for(key: str) -> None:
    """So a rename leaves the set above red rather than passing over a key nobody sends."""
    aliases = {field.alias or name for name, field in OperationResponse.model_fields.items()}

    assert key in aliases
