"""``Idempotency-Key`` as the document declares it, crossed against the routes that read it.

Two surfaces have to agree. ``get_idempotency_guard`` takes the key as an annotated ``Header``
parameter, so the framework declares ``Idempotency-Key`` on every operation whose dependency tree
resolves it, and ``frontend/src/api/schema.d.ts`` is generated from the document, so that
declaration is the whole of what lets a generated client type the header rather than remember it.

The crossing is an equality, in both directions, over two documents: the one the runtime serves and
the one committed for the client generator. Declaring without carrying is as wrong as carrying
without declaring, because the first types a header no route reads.

**Asserted by walking each operation's own ``parameters`` list, never by searching the document's
text.** One route's summary says it needs the header, so a text search answers true for a document
in which nothing at all is declared, which is the state this crossing was written against. The
reader is controlled against that trap and against a header declared under another name, because
each of its two predicates is the only thing in the tree that catches its own defect.

What this file cannot do, stated beside what it can: it reads declarations, not behavior. An api
that declared the header and then ignored it would pass here, which is why the dependency's own
tests drive a key through the guard. Nothing here crosses the declaration against what the browser
client sends either, so a client sending the header to a route that declares none is outside this
file's reach.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import APIRouter, FastAPI

from syncr_api.core.schemas import WireModel
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.idempotency.injection import (
    IdempotencyGuardDep,
    get_idempotency_guard,
    require_idempotency_key,
)
from tests.boundaries import api_routes, resolved_dependencies, route_identity
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from fastapi.testclient import TestClient

# The committed contract, resolved through the same anchor every figure about this ticket was
# printed against: the installed package, not this file's own depth in the tree.
CONTRACT = repo_root() / "frontend" / "openapi.json"

# The two dependencies that read the key. Either one declares the header, so a route carrying
# either is a route the document must describe.
KEY_READERS = frozenset({get_idempotency_guard, require_idempotency_key})

# The keys of an OpenAPI path item that are operations. A path item may also hold `summary`,
# `description`, `servers` and a shared `parameters` list, none of which is one.
OPERATION_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


class Answered(WireModel):
    """A response body, so the synthetic routes in the census control have a declared shape."""

    ok: bool


# The three parameter declarations the reader must tell apart, and the one it must accept.
THE_HEADER = {"in": "header", "name": IDEMPOTENCY_KEY_HEADER}
HEADER_NAMED_OTHERWISE = {"in": "header", "name": "X-Other"}
QUERY_OF_THAT_NAME = {"in": "query", "name": IDEMPOTENCY_KEY_HEADER}


def carrying_operations(app: FastAPI) -> set[tuple[str, str]]:
    """Every ``(method, path)`` whose dependency tree resolves one of the two key readers.

    Read off the route table rather than from a list of paths, so a route that starts or stops
    carrying the guard changes this answer without anyone remembering to edit it.
    """
    return {
        identity
        for route in api_routes(app)
        for identity in route_identity(route)
        if resolved_dependencies(route) & KEY_READERS
    }


def declaring_operations(document: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Every ``(method, path)`` whose own parameters list declares the header."""
    return {
        (method.upper(), path)
        for path, path_item in document["paths"].items()
        for method, operation in path_item.items()
        if method in OPERATION_METHODS
        and any(
            parameter["in"] == "header" and parameter["name"] == IDEMPOTENCY_KEY_HEADER
            for parameter in operation.get("parameters", ())
        )
    }


def served_document(client: TestClient) -> Mapping[str, Any]:
    """The document the runtime serves, which is what a client generated today would read."""
    answered = client.get("/openapi.json")
    assert answered.status_code == HTTPStatus.OK, answered.text
    document: Mapping[str, Any] = answered.json()
    return document


def committed_document(_client: TestClient) -> Mapping[str, Any]:
    """The document in the tree, which is what the committed client WAS generated from."""
    document: Mapping[str, Any] = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return document


DOCUMENTS: Mapping[str, Callable[[TestClient], Mapping[str, Any]]] = {
    "served": served_document,
    "committed": committed_document,
}


def test_the_application_has_operations_that_this_file_examines(app: FastAPI) -> None:
    # Every crossing below is an equality between two derived sets, so all of them hold vacuously
    # if the census reaches nothing. This is the control for that, and it names both dependencies
    # because the stricter one is a single route and a census could miss exactly it.
    carrying = carrying_operations(app)
    demanding = {
        identity
        for route in api_routes(app)
        for identity in route_identity(route)
        if require_idempotency_key in resolved_dependencies(route)
    }

    assert carrying, "no route carries either idempotency dependency, so nothing was examined"
    assert demanding, "no route demands a key, so the stricter of the two dependencies is unread"
    assert demanding < carrying, (
        f"every route that carries the guard also demands a key ({sorted(carrying)}), so the "
        "census cannot tell the two dependencies apart"
    )


@pytest.mark.parametrize("read_document", DOCUMENTS.values(), ids=DOCUMENTS.keys())
def test_the_operations_declaring_the_key_are_exactly_the_ones_that_read_it(
    app: FastAPI,
    client: TestClient,
    read_document: Callable[[TestClient], Mapping[str, Any]],
) -> None:
    carrying = carrying_operations(app)
    declared = declaring_operations(read_document(client))

    assert declared == carrying, (
        f"{len(carrying)} operations read the key and {len(declared)} declare "
        f"{IDEMPOTENCY_KEY_HEADER}. Carrying a dependency and declaring nothing: "
        f"{sorted(carrying - declared)}. Declaring a header no route reads: "
        f"{sorted(declared - carrying)}. Regenerate with `just contract`."
    )


def test_the_census_answers_from_the_dependency_tree_rather_than_from_a_list_of_paths() -> None:
    # The positive control for the census itself, and the one no mutation of this file can supply:
    # narrowing the census to nothing leaves the equality above green, because the real document
    # was generated from the same dependency tree the census reads. A synthetic app with one route
    # of each kind separates a census that discriminates from one that matches nothing.
    router = APIRouter()

    @router.post("/reads-the-key")
    async def reads_the_key(guard: IdempotencyGuardDep) -> Answered:
        return Answered(ok=guard is not None)

    @router.post("/reads-no-key")
    async def reads_no_key() -> Answered:
        return Answered(ok=True)

    synthetic = FastAPI()
    synthetic.include_router(router)

    assert carrying_operations(synthetic) == {("POST", "/reads-the-key")}
    assert declaring_operations(synthetic.openapi()) == {("POST", "/reads-the-key")}


def test_the_declaration_reader_answers_from_a_header_parameter_of_that_name_alone() -> None:
    # The census above has controls; its counterpart, the reader of the document, needs its own,
    # because each of its two predicates is the sole detector of a defect nothing else in the tree
    # catches. Dropping the name check hides a header declared under another name, which is what a
    # missing alias produces; dropping the location check counts a query parameter that merely
    # shares the name. The last case is the positive control: without it a reader that answered
    # nothing at all would pass every line above it.
    text_only = {"paths": {"/says-it": {"post": {"summary": f"Needs an {IDEMPOTENCY_KEY_HEADER}"}}}}
    wrong_name = {"paths": {"/other": {"post": {"parameters": [HEADER_NAMED_OTHERWISE]}}}}
    wrong_place = {"paths": {"/query": {"post": {"parameters": [QUERY_OF_THAT_NAME]}}}}
    declared = {"paths": {"/declares": {"post": {"parameters": [THE_HEADER]}}}}

    assert declaring_operations(text_only) == set(), "a text search is not a parameter walk"
    assert declaring_operations(wrong_name) == set(), "a header of another name is not this one"
    assert declaring_operations(wrong_place) == set(), "a query parameter is not a header"
    assert declaring_operations(declared) == {("POST", "/declares")}
