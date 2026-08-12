"""The 409 the concession module declares, crossed against the routes that can send one.

The generated client's types come from the document, so a route declaring a status it cannot answer
types a response no caller can receive, and a route answering one it does not declare hands the
client no type at all. Both are invisible from either file on its own, which is what this crosses.

**Three readings, and no two derived from each other.** The endpoints are read from
``concessions/api.py`` as text, so a route added in a module nothing imports is still seen. The
refusals are read from ``concessions/service.py`` as text, following the one module-level helper a
method delegates a refusal to. The declarations are read from the document, in both versions: the
one the runtime serves and the one committed for the client generator, so a declaration changed in
the code and left in the committed file reddens rather than waiting for CI.

**What is NOT here is the wire.** That a request for a tradeoff against a week with no solve to
concede against really answers 409, and that one behind a running solve answers 202, is driven
against a real database and a real request in ``test_concession_routes_integration.py``. This file
answers the other half: whether the document says so.
"""

from __future__ import annotations

import ast
import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest

from syncr_api.concessions.wiring import CONCESSIONS_TAG
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from fastapi.testclient import TestClient

CONTRACT = repo_root() / "frontend" / "openapi.json"

# The name a route handler binds its service to, which is the parameter every handler here takes.
SERVICE_PARAMETER = "service"

# The refusal a route may answer with beyond the set every route in the application answers.
CONFLICT = str(HTTPStatus.CONFLICT.value)

# The exception class a 409 is raised as. Read as a name rather than imported, because what is being
# read is the source of a module this test must not depend on the runtime behavior of.
CONFLICT_CLASS = "Conflict"


def module_source(source_root: Path, name: str) -> str:
    return (source_root / "concessions" / name).read_text(encoding="utf-8")


def service_method_called_in(body: list[ast.stmt]) -> str | None:
    """The one service method a route handler calls, or nothing when it calls none.

    ``api.py``'s own contract is that a handler calls exactly one, which
    ``test_authorization_boundary.py`` holds from the other side: what this needs is which one, so
    that a route's declared statuses can be crossed against the method behind it.
    """
    called = {
        node.func.attr
        for node in ast.walk(ast.Module(body=body, type_ignores=[]))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == SERVICE_PARAMETER
    }
    if len(called) != 1:
        return None
    return called.pop()


def handlers_by_name(source: str) -> Mapping[str, str]:
    """Every route handler in ``api.py``, and the service method it calls.

    Keyed by the handler's own name, because that is what the document derives its operation id
    from: a handler renamed without its declaration moving reads as a route this crossing cannot
    account for rather than as one it silently skips.
    """
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if not any(_is_a_route(decorator) for decorator in node.decorator_list):
            continue
        method = service_method_called_in(node.body)
        assert method is not None, (
            f"{node.name} calls no single service method, so what it can refuse cannot be read "
            "from the service. A handler that calls two is a handler this crossing cannot account "
            "for."
        )
        found[node.name] = method
    return found


def _is_a_route(decorator: ast.expr) -> bool:
    """Whether a decorator is a router's own verb, whichever router the module hangs it on."""
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
    )


def methods_that_can_refuse(source: str) -> set[str]:
    """Every service method that can raise a conflict, its own body or a helper it delegates to.

    One level of delegation, because that is the shape the module uses: the week-has-no-solve
    refusal is a module-level function the request path calls before it asks for a solve. A second
    level would need a call graph, and a method that gained one would read here as refusing nothing,
    which is the failure this reading's own control drives.
    """
    tree = ast.parse(source)
    refusing_helpers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _raises_a_conflict(node)
    }
    refusing: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if _raises_a_conflict(node) or _calls_one_of(node, refusing_helpers):
            refusing.add(node.name)
    return refusing


def _raises_a_conflict(node: ast.AST) -> bool:
    return any(
        isinstance(statement, ast.Raise)
        and isinstance(statement.exc, ast.Call)
        and isinstance(statement.exc.func, ast.Name)
        and statement.exc.func.id == CONFLICT_CLASS
        for statement in ast.walk(node)
    )


def _calls_one_of(node: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(called, ast.Call)
        and isinstance(called.func, ast.Name)
        and called.func.id in names
        for called in ast.walk(node)
    )


def declared_conflicts(document: Mapping[str, Any]) -> Mapping[str, bool]:
    """Whether each concession operation declares a 409, keyed by its operation id."""
    return {
        operation["operationId"]: CONFLICT in operation.get("responses", {})
        for methods in document["paths"].values()
        for operation in methods.values()
        if CONCESSIONS_TAG in (operation.get("tags") or ())
    }


def served_document(client: TestClient) -> Mapping[str, Any]:
    answered = client.get("/openapi.json")
    assert answered.status_code == HTTPStatus.OK, answered.text
    document: Mapping[str, Any] = answered.json()
    return document


def committed_document() -> Mapping[str, Any]:
    document: Mapping[str, Any] = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return document


def operation_id_of(handler: str, declared: Mapping[str, bool]) -> str:
    """The document's id for one handler, which it derives from the handler's own name."""
    matching = [one for one in declared if one.startswith(f"{handler}_")]
    assert len(matching) == 1, (
        f"{handler} matches {matching} in the document, so the crossing cannot say which "
        "declaration belongs to it"
    )
    return matching[0]


def test_the_crossing_reads_something_on_every_side(source_root: Path, client: TestClient) -> None:
    """The floor. Every assertion below is an equality between derived sets.

    A reading that went blind would satisfy them all: no handler found, no refusal found, and no
    declaration found agree perfectly. The last two are the ones with teeth, because they are what
    makes the equality below a discrimination rather than a restatement: some method here refuses
    and some method here cannot.
    """
    handlers = handlers_by_name(module_source(source_root, "api.py"))
    refusing = methods_that_can_refuse(module_source(source_root, "service.py"))
    declared = declared_conflicts(served_document(client))

    assert len(handlers) == len(declared), (
        f"{len(handlers)} handler(s) read from the source and {len(declared)} operation(s) tagged "
        f"{CONCESSIONS_TAG} in the document: {sorted(handlers)} against {sorted(declared)}"
    )
    called = set(handlers.values())
    assert called & refusing, f"no method of {sorted(called)} was read as able to refuse"
    assert called - refusing, f"every method of {sorted(called)} was read as able to refuse"


@pytest.mark.parametrize("read_document", ["served", "committed"])
def test_a_route_declares_a_conflict_exactly_when_its_service_can_raise_one(
    source_root: Path, client: TestClient, read_document: str
) -> None:
    """The crossing, over both versions of the document.

    Declaring a 409 a route cannot answer types a response no caller receives; answering one it does
    not declare leaves the generated client no type for a refusal a reader will see. The equality
    holds in both directions for exactly that reason.
    """
    handlers = handlers_by_name(module_source(source_root, "api.py"))
    refusing = methods_that_can_refuse(module_source(source_root, "service.py"))
    document = served_document(client) if read_document == "served" else committed_document()
    declared = declared_conflicts(document)

    for handler, method in handlers.items():
        can_refuse = method in refusing
        declares = declared[operation_id_of(handler, declared)]
        assert declares == can_refuse, (
            f"{handler} calls {method}, which {'can' if can_refuse else 'cannot'} raise a "
            f"{CONFLICT_CLASS}, and the {read_document} document "
            f"{'declares' if declares else 'declares no'} {CONFLICT}. Regenerate with "
            "`just contract` and commit frontend/openapi.json with frontend/src/api/schema.d.ts."
        )


def test_the_refusal_reading_answers_from_a_raise_or_one_delegation() -> None:
    # The reader's own control, and the one no edit to the module can supply: a reading that
    # answered nothing leaves the crossing above vacuous in one direction, and one that answered
    # everything leaves it vacuous in the other. Each input is a shape this file has to tell apart.
    direct = "class S:\n    async def request(self):\n        raise Conflict('no')\n"
    delegated = (
        "class S:\n    async def request(self):\n        _require(self)\n\n"
        "def _require(week):\n    raise Conflict('no')\n"
    )
    caught = "class S:\n    async def request(self):\n        raise ValidationFailed('no')\n"
    mentioned = "class S:\n    async def request(self):\n        return Conflict\n"
    unrelated_helper = (
        "class S:\n    async def request(self):\n        _fine(self)\n\n"
        "def _fine(week):\n    return None\n"
    )

    assert methods_that_can_refuse(direct) == {"request"}
    assert methods_that_can_refuse(delegated) == {"request", "_require"}
    assert "request" not in methods_that_can_refuse(caught)
    assert "request" not in methods_that_can_refuse(mentioned)
    assert "request" not in methods_that_can_refuse(unrelated_helper)


def test_the_handler_reading_answers_from_a_route_decorator_and_one_service_call() -> None:
    # The other reader's control. A handler bound to a second router is still a handler, which is
    # what the split into two routers made possible, and a function with no route decorator is not
    # one however much it looks like a handler.
    on_one_router = (
        "@router.post(PATH)\nasync def request_tradeoff(service: Dep):\n"
        "    return await service.request(1)\n"
    )
    on_another_router = (
        "@adjustment_router.get(PATH)\nasync def list_adjustments(service: Dep):\n"
        "    return await service.approved(1)\n"
    )
    undecorated = "async def helper(service: Dep):\n    return await service.request(1)\n"

    assert handlers_by_name(on_one_router) == {"request_tradeoff": "request"}
    assert handlers_by_name(on_another_router) == {"list_adjustments": "approved"}
    assert handlers_by_name(undecorated) == {}
