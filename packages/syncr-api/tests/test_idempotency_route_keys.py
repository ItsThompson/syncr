"""The claim's route key: one per guarded handler, and no two the same.

A claim is ``(tenant_id, route, idempotency_key)``. ``route`` is a constant the handler passes to
``guard.once``, so two handlers on one path are separated by that constant and by nothing else: the
request hash carries the addressed path and the body, and neither knows the method. Two handlers
sharing a route key would therefore share a claim, and if they also share a path they would share
the whole hash, so one key sent to both would replay the first one's response.

Nothing else in the suite states that. The keys are constants spread over ten modules, and a new
handler is written by mirroring its nearest sibling, which is how a duplicate would arrive.

The key is resolved per guarded route rather than by scanning the tree for ``guard.once``, so the
route set comes from the application, and a guarded route whose key cannot be resolved fails here
instead of quietly leaving the set. That is also why no count appears below: the coverage work adds
guarded routes, and distinctness is the property.

A route key built per resource (``guard.once(f"{DROP_ROUTE}:{task_id}", ...)``) is refused rather
than resolved. It scopes one route's claim by hand and leaves every route of the same shape as it
was.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from syncr_api.core.app_factory import create_app
from syncr_api.idempotency.injection import get_idempotency_guard, require_idempotency_key
from tests.boundaries import api_routes, resolved_dependencies

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import FastAPI

    from syncr_api.core.settings import ServiceSettings

# Either dependency builds the guard, so a route resolving either one takes a claim.
KEY_READERS = frozenset({get_idempotency_guard, require_idempotency_key})

# Stands in for a feature module's own constant, so the refused shape below is the real one.
DROP_ROUTE = "tasks.drop"

COMPUTED_KEY = (
    "passes a computed route key to guard.once. The addressed resource belongs in the request "
    "hash, which every route shares, rather than in one route's claim"
)
NO_ROUTE_KEY = (
    "resolves the idempotency guard and passes no route key this check can resolve. Extend the "
    "resolution rather than leaving the route out of the pairwise comparison"
)


def route_key_of(endpoint: Callable[..., object]) -> str:
    """The route key this handler claims under, read off its own call to ``guard.once``."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if not isinstance(called, ast.Attribute) or called.attr != "once" or not node.args:
            continue
        named = node.args[0]
        if not isinstance(named, ast.Name):
            raise AssertionError(f"{endpoint.__qualname__} {COMPUTED_KEY}")
        return str(getattr(sys.modules[endpoint.__module__], named.id))
    raise AssertionError(f"{endpoint.__qualname__} {NO_ROUTE_KEY}")


def guarded_route_keys(app: FastAPI) -> dict[str, str]:
    """Every guarded route's key, by the handler that claims under it."""
    return {
        route.endpoint.__qualname__: route_key_of(route.endpoint)
        for route in api_routes(app)
        if resolved_dependencies(route) & KEY_READERS
    }


def test_no_two_guarded_handlers_claim_under_one_route_key(settings: ServiceSettings) -> None:
    claimed = guarded_route_keys(create_app(settings))

    assert claimed, "no guarded route was found, so the comparison below holds vacuously"
    keys = list(claimed.values())
    shared = sorted({key for key in keys if keys.count(key) > 1})
    assert not shared, (
        f"these route keys are claimed by more than one handler: {shared}. Two handlers sharing a "
        "key share a claim, so one key sent to both replays the first one's response."
    )


def test_a_computed_route_key_is_refused() -> None:
    # The control on the resolution, over a handler shaped like the per-route fix rather than a real
    # route. Without it, a resolver that raised on nothing would pass the comparison above.
    async def drop_a_task_the_wrong_way(guard: Any, task_id: str) -> None:
        await guard.once(f"{DROP_ROUTE}:{task_id}", None, None)

    with pytest.raises(AssertionError, match="computed route key"):
        route_key_of(drop_a_task_the_wrong_way)


def test_a_guarded_handler_that_claims_nothing_is_refused() -> None:
    # The second control: a route resolving the guard and claiming nothing would otherwise drop out
    # of the set and shrink it silently.
    async def declare_a_thing_without_claiming(guard: Any) -> None:
        assert guard is not None

    with pytest.raises(AssertionError, match="no route key"):
        route_key_of(declare_a_thing_without_claiming)
