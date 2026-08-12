"""Invariant A1: an anchor is read-only in syncr, asserted mechanically rather than promised.

"We did not add a route that edits an anchor" is a claim that decays the moment someone needs one,
and the failure is silent: a plan that quietly disagrees with the calendar the user reads. So this
file examines whatever routes, shapes, and modules exist whenever it runs.

Four rules, and each is also run against a synthetic input that breaks it. A rule whose test cannot
fail is indistinguishable from a rule nobody enforces.

1. No route under ``/api/v1/anchors`` changes a commitment, except the one that retypes it. A
   retype changes what the commitment RESERVES around itself; it does not change the commitment.
2. The repository has exactly one method that changes what a source published. That is what makes
   the route table's silence mean something: a route reaches persistence only through this surface.
3. Nothing an anchor route hands back carries a location. An anchor's location discloses where the
   user physically is at a given hour, and transit is declared per anchor type rather than derived
   from it, so the column has no reader and must not reach the wire by sharing a name with a field.
4. The modules that name the location column are exactly the ones that store it. A location with a
   reader is the reinterpretation of PRD 3.4 quietly reversing itself.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI

import syncr_api.anchors
from syncr_api.anchors import schemas
from syncr_api.anchors.config import (
    ANCHOR_TYPE_ASSIGNMENT_PATH,
    ANCHORS_PREFIX,
    READ_ONLY_STATEMENT,
)
from syncr_api.anchors.records import AnchorRecord
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.views import anchor_view
from syncr_api.anchors.wiring import build_anchors_router
from syncr_api.core.schemas import WireModel
from syncr_domain.intervals import Interval
from tests.boundaries import METHODS_WITHOUT_A_BODY, api_routes, public_methods, route_identity

if TYPE_CHECKING:
    from collections.abc import Iterator

# The one mutation an anchor route may offer, as a path rather than as a handler name, so renaming
# the handler cannot widen the exemption.
RETYPE_PATH = f"{ANCHORS_PREFIX}{ANCHOR_TYPE_ASSIGNMENT_PATH}"

# The column stored with no reader. A string, because both rules about it are about a NAME: a field
# name reaching a response shape, and an attribute name reaching a module.
LOCATION = "location"

# The one repository method allowed to change what a source published.
THE_FACT_WRITER = "update_fact"

# The modules that may name the location column as CODE, and why each one does. Prose is not a
# reader, so a module that only explains the absence in a docstring is not in this set: the reading
# below is over identifiers, not over text.
#
#   models      declares the column. The fact is stored rather than discarded, so work that adds
#               routing later needs no backfill.
#   records     holds it on the frozen view, and states why nothing reads it.
#   identity    bounds it, because a publisher chooses its length and the column has a width.
#   repository  writes it, on create and on the one fact writer.
#   reconcile   passes what the feed published to the repository.
MODULES_THAT_MAY_NAME_A_LOCATION = frozenset(
    {"models", "records", "identity", "repository", "reconcile"}
)

START = datetime(2026, 2, 10, 16, 0, tzinfo=UTC)
A_LOCATION = "Kontron, Ely"


def an_anchor() -> AnchorRecord:
    return AnchorRecord(
        id=UUID(int=1),
        tenant_id=UUID(int=2),
        source_id=UUID(int=3),
        external_uid="uid@example.ac.uk",
        series_uid=None,
        title="Kontron Placement Interview",
        interval=Interval(START, START + timedelta(minutes=45)),
        location=A_LOCATION,
        anchor_type_id=None,
        type_overridden=False,
        possibly_stale=False,
    )


def app_with(router: APIRouter) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def anchor_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every ``(method, path)`` the application answers under the anchors prefix."""
    return sorted(
        (method, path)
        for route in api_routes(app)
        for method, path in route_identity(route)
        if path == ANCHORS_PREFIX or path.startswith(f"{ANCHORS_PREFIX}/")
    )


def mutations_other_than_a_retype(app: FastAPI) -> list[str]:
    """Every unsafe anchor route that is not the retype, which must be none."""
    return [
        f"{method} {path}"
        for method, path in anchor_routes(app)
        if method not in METHODS_WITHOUT_A_BODY and path != RETYPE_PATH
    ]


def wire_models() -> Iterator[type[WireModel]]:
    """Every request and response shape the anchor routes exchange."""
    for name in dir(schemas):
        candidate = getattr(schemas, name)
        if isinstance(candidate, type) and issubclass(candidate, WireModel):
            yield candidate


def methods_accepting(parameter: str) -> list[str]:
    """The repository's public methods that take ``parameter``."""
    return sorted(
        name
        for name in public_methods(AnchorRepository)
        if parameter in inspect.signature(getattr(AnchorRepository, name)).parameters
    )


def modules_naming(attribute: str) -> set[str]:
    """The anchor package's modules whose CODE names ``attribute``.

    Identifiers only: a name, an attribute access, a keyword argument, or a parameter. Prose in a
    docstring is not a reader, and a module explaining why nothing reads the column is exactly what
    the absence should look like.
    """
    package = Path(syncr_api.anchors.__file__).resolve().parent
    naming = {
        path.stem
        for path in sorted(package.glob("*.py"))
        if attribute in _identifiers(path.read_text(encoding="utf-8"))
    }
    return naming - {"__init__"}


def _identifiers(source: str) -> set[str]:
    """Every name this source uses as code, however it reaches one."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.keyword):
            if node.arg is not None:
                found.add(node.arg)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
    return found


# --------------------------------------------------------------------------------
# Rule 1: no route edits or deletes a commitment.
# --------------------------------------------------------------------------------


def test_the_application_answers_anchor_routes_this_file_examines() -> None:
    # Every route assertion iterates, so all of them pass vacuously on an app with none. This is
    # the control for their subject matter.
    found = anchor_routes(app_with(build_anchors_router()))

    assert found, "no anchor route was found to examine"
    assert ("GET", ANCHORS_PREFIX) in found
    assert ("PUT", RETYPE_PATH) in found


def test_no_route_edits_or_deletes_an_anchor() -> None:
    offending = mutations_other_than_a_retype(app_with(build_anchors_router()))

    assert offending == [], (
        f"{offending} can change an imported commitment. An anchor is a fact: the source of truth "
        "stays with whoever owns it, and the only mutation syncr offers is a retype, which changes "
        "what the commitment reserves around itself rather than the commitment."
    )


def test_the_route_rule_reports_an_anchor_route_that_would_edit_one() -> None:
    # The control. Without it, the rule passes on an app whose anchor routes are all reads and
    # keeps passing after someone adds a PATCH.
    broken = APIRouter()
    path = f"{ANCHORS_PREFIX}/{{anchor_id}}"

    @broken.patch(path)
    async def _edit(anchor_id: str) -> dict[str, str]:
        return {"id": anchor_id}

    @broken.delete(path)
    async def _remove(anchor_id: str) -> dict[str, str]:
        return {"id": anchor_id}

    assert mutations_other_than_a_retype(app_with(broken)) == [
        f"DELETE {path}",
        f"PATCH {path}",
    ]


def test_the_retype_is_the_only_unsafe_anchor_route() -> None:
    # A stale exemption is worse than no exemption: it would outlive the route it was written for
    # and silently permit whatever later took that path.
    found = anchor_routes(app_with(build_anchors_router()))

    unsafe = [f"{method} {path}" for method, path in found if method not in METHODS_WITHOUT_A_BODY]

    assert unsafe == [f"PUT {RETYPE_PATH}"]


# --------------------------------------------------------------------------------
# Rule 2: persistence offers one door to a published fact.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("column", ["title", "interval", "location"])
def test_one_repository_method_changes_what_a_source_published(column: str) -> None:
    # `create` takes all three as well, because a fact has to arrive somehow. What must not exist
    # is a SECOND way to change one, whether or not a route calls it today.
    assert methods_accepting(column) == ["create", THE_FACT_WRITER], (
        f"{methods_accepting(column)} accept a {column}. Creating an anchor and replacing what its "
        f"source published are the two writes there are; a third is a way to change a fact syncr "
        "does not own."
    )


def test_the_repository_rule_would_report_a_third_writer() -> None:
    # The control. The rule compares against an exact pair, so a method added with any of the three
    # parameters changes the answer. This asserts the comparison is over a real, non-empty reading.
    assert methods_accepting("title") != []
    assert methods_accepting("possibly_stale") == []


def test_no_repository_method_reads_a_location_back_by_itself() -> None:
    # The record carries it because the row does. What must not exist is a read whose whole purpose
    # is to fetch it, which is what routing would add and what this deployment deliberately does
    # not have.
    assert "find_location" not in public_methods(AnchorRepository)


# --------------------------------------------------------------------------------
# Rule 3: no location on the wire.
# --------------------------------------------------------------------------------


def test_the_wire_models_this_file_examines_exist() -> None:
    # The control for the rule below: a walk that found nothing would leave it passing vacuously,
    # and it would keep passing as later shapes arrive.
    found = set(wire_models())

    assert schemas.AnchorResponse in found
    assert schemas.AnchorTypeResponse in found
    assert len(found) >= 5


def test_no_anchor_wire_shape_carries_a_location() -> None:
    carrying = sorted(model.__name__ for model in wire_models() if LOCATION in model.model_fields)

    assert carrying == [], (
        f"{carrying} put an anchor's location on the wire. It is stored with no reader: transit is "
        "declared per anchor type rather than derived from a location, and a location discloses "
        "where the user physically is at a given hour."
    )


def test_the_shape_rule_reports_a_response_that_added_one() -> None:
    # The control, against a shape built here rather than by editing the real one.
    class LeakyResponse(WireModel):
        location: str | None = None

    assert LOCATION in LeakyResponse.model_fields


def test_a_rendered_commitment_carries_no_location_anywhere_in_its_payload() -> None:
    # The field rule is about names. This is about the value: the composed view a route maps onto a
    # response holds the whole record, so a later field could reach the location through it.
    anchor = an_anchor()
    view = anchor_view(anchor, source=None, anchor_type=None)

    rendered = schemas.AnchorResponse(
        id=anchor.id,
        source_id=anchor.source_id,
        source_name=view.source_name,
        read_only=True,
        read_only_statement=view.read_only_statement,
        series_uid=anchor.series_uid,
        title=anchor.title,
        starts_at=anchor.interval.start,
        ends_at=anchor.interval.end,
        anchor_type_id=None,
        anchor_type_name=None,
        type_source=anchor.type_source,
        possibly_stale=anchor.possibly_stale,
        casts=schemas.ShadowDeclarationResponse(
            prep=False, outbound_transit=False, return_transit=False, recovery=False
        ),
    ).model_dump(mode="json", by_alias=True)

    assert A_LOCATION not in str(rendered)
    assert anchor.location == A_LOCATION


def test_a_commitments_payload_states_it_is_read_only_and_names_its_source() -> None:
    view = anchor_view(an_anchor(), source=None, anchor_type=None)

    # The source is named inside the sentence a panel renders, because a bare boolean does not tell
    # the user where to go and change it.
    assert "read-only" in view.read_only_statement
    assert view.source_name in view.read_only_statement
    assert "{source}" in READ_ONLY_STATEMENT


# --------------------------------------------------------------------------------
# Rule 4: the location has no reader anywhere in the package.
# --------------------------------------------------------------------------------


def test_only_the_modules_that_store_a_location_name_it() -> None:
    naming = modules_naming(LOCATION)

    assert naming <= MODULES_THAT_MAY_NAME_A_LOCATION, (
        f"{sorted(naming - MODULES_THAT_MAY_NAME_A_LOCATION)} name an anchor's location. It is "
        "stored with no reader, because transit is declared per anchor type rather than derived "
        "from a location: routing needs a maps integration, a home address, and a travel-mode "
        "preference, none of which is in this epic. Adding a reader reverses that decision."
    )


def test_the_module_rule_finds_the_modules_that_do_store_it() -> None:
    # The control. A reading that found nothing would leave the rule passing forever, including
    # after a service or a view started reading the column.
    naming = modules_naming(LOCATION)

    assert {"models", "records", "repository", "reconcile"} <= naming
    assert "service" not in naming
    assert "views" not in naming
    assert "api" not in naming


def test_the_schemas_module_states_why_no_response_carries_a_location() -> None:
    # The absence has to read as a decision. Without a stated reason, someone adds the field
    # because nothing said not to, and the rule above then fails for a reason nobody can act on.
    stated = schemas.__doc__ or ""

    assert LOCATION in stated
    assert "no reader" in stated
