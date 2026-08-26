"""The one declaration of a live tenant's minimum, and a walk that keeps it one.

Every suite that drives a runner against a live tenant once kept its own private copy of
"the least a plan can exist from", and the copies drifted into different answer shapes while
seeding the same rows. :mod:`tests.live_minimums` holds the one copy now, so what enforces
"one" is not discipline but a reading of the tests directory that examines whatever modules
exist whenever it runs.

**What counts as a declaration of the minimum** is mechanical: an async function named
``declare_the_minimum`` whose body seeds the day shape AND the week pattern through the
template repositories. That reading excludes the two same-named helpers that are genuinely
different mechanisms -- the route-level declaration that seeds through an HTTP client, and
the netting suite's variant that overrides the Area's identifier and bumps a week-input
version -- neither of which declares a day shape or a week pattern at all. A sixth private
copy of the full declaration fails this walk the moment it lands.

The walk returns data rather than asserting, so the real tree AND a deliberately planted
second copy both drive it. A walk with no positive control passes forever once it has gone
blind, which is worse than having no walk at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.live_minimums import AREA_NAME

# The one module the declaration lives in, and the name every private copy took.
DECLARATION_NAME = "declare_the_minimum"
THE_ONE_MODULE = "live_minimums.py"

# A declaration seeds the day shape and the week pattern through these repositories. Both
# names must appear in the body: the route-level and netting-suite variants share the name
# but seed neither, and the walk reads bodies rather than signatures for exactly that reason.
DAY_SHAPE_SEEDER = "DayTypeRepository"
WEEK_PATTERN_SEEDER = "WeekPatternRepository"


def declarations_of_the_minimum(source: str) -> list[ast.AsyncFunctionDef]:
    """Every async ``declare_the_minimum`` in one source that seeds the full minimum.

    Returns the matching definitions rather than a count, so a caller can read where a
    violation sits instead of learning only that one exists.
    """
    found: list[ast.AsyncFunctionDef] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != DECLARATION_NAME:
            continue
        called = {
            getattr(item.func, "id", "") for item in ast.walk(node) if isinstance(item, ast.Call)
        }
        if DAY_SHAPE_SEEDER in called and WEEK_PATTERN_SEEDER in called:
            found.append(node)
    return found


def declarations_by_module(tests_root: Path) -> dict[str, int]:
    """How many declarations each top-level module under the tests directory holds."""
    found: dict[str, int] = {}
    for path in sorted(tests_root.glob("*.py")):
        count = len(declarations_of_the_minimum(path.read_text(encoding="utf-8")))
        if count:
            found[path.name] = count
    return found


A_PRIVATE_COPY = f"""
async def declare_the_minimum(sessions, tenant_id) -> None:
    async with sessions() as session, session.begin():
        await {DAY_SHAPE_SEEDER}(session, tenant_id).create(name="Weekday", created_at=None)
        await {WEEK_PATTERN_SEEDER}(session, tenant_id).replace(pattern)
"""


def test_the_real_tree_holds_exactly_one_declaration_and_names_its_module() -> None:
    by_module = declarations_by_module(Path(__file__).resolve().parent)
    assert by_module == {THE_ONE_MODULE: 1}


def test_a_planted_second_copy_is_seen() -> None:
    assert len(declarations_of_the_minimum(A_PRIVATE_COPY + A_PRIVATE_COPY)) == 2


def test_a_same_named_helper_that_seeds_no_day_shape_is_not_a_declaration() -> None:
    route_level = (
        "async def declare_the_minimum(client, headers, sessions, tenant_id) -> None:\n"
        '    area = await client.post("/areas", json={"name": "' + AREA_NAME + '"})\n'
        "    await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=None)\n"
    )
    assert declarations_of_the_minimum(route_level) == []
