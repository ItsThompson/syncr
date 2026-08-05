"""OP7, asserted rather than argued: conflict detection reaches no off-plan read.

"An anchor overlapping a pinned block **inside an off-plan span is still a conflict. No special
case.**" A commitment during a period the user declared off is still a commitment, and a pinned
block inside one is still the user's own edit, so the collision is raised: off-plan suspends syncr's
scheduling, not the world's.

That rule is satisfied by an ABSENCE: nothing on the detection path consults an off-plan span. An
absence is what a behavioural test cannot pin, because there is no branch to revert, so a test
asserting "a conflict is raised inside a declared span" passes identically whether the suppression
is missing or merely inactive for that fixture. What can be asserted is the absence itself, and this
package's boundary framework exists for that. Two lenses, because neither sees what the other does:

**The import closure**, in a subprocess, because ``sys.modules`` is process-global and a sibling
test importing the off-plan package would otherwise answer for this one. It catches a suppression
reached transitively through a module the detection already imports, which no source read of two
files could see.

**The source**, because the suppressing call is reachable without importing the off-plan package at
all: ``calendar_occupancy`` takes an ``OffPlanSuppression`` its caller supplies and imports the type
for annotations only. The detection deliberately calls the shadow generator directly instead, and
that choice is what this lens holds.

Each has a positive control. A boundary test with no positive control passes forever once the thing
it guards has been removed, which is worse than having no test at all.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

# The two modules the detection is made of: the pure detector, and the ingest pass that feeds it.
DETECTION_MODULES: Final = ("syncr_api.plans.overlaps", "syncr_api.conflicts.ingest")

# A module that DOES reach the off-plan package, as the control for the import lens. The budget
# service reads declared spans out of it to subtract them from the discretionary denominator, which
# is the reading the detection must not perform. Deliberately not the week assembler: it takes its
# spans as values and imports the package for annotations only, so it would prove nothing here.
READS_OFF_PLAN: Final = "syncr_api.budgets.service"

OFF_PLAN_PACKAGE: Final = "syncr_api.offplan"

# What applying a suppression looks like in source, whichever way it is reached.
# `calendar_occupancy` is the function that drops a derived block inside a declared span, and
# `suppresses_content` is the predicate it asks; either name here would mean a span was consulted.
SUPPRESSING_CALLS: Final = frozenset({"calendar_occupancy", "suppresses_content"})

_PROBE = """
import importlib, json, sys

for name in {modules!r}:
    importlib.import_module(name)

print(json.dumps(sorted(name for name in sys.modules if {package!r} in name)))
"""


def off_plan_modules_loaded_by(*modules: str) -> list[str]:
    """The off-plan modules importing ``modules`` in a fresh process pulls in."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", _PROBE.format(modules=list(modules), package=OFF_PLAN_PACKAGE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"the probe could not import {modules}: {completed.stderr}"
    loaded: list[str] = json.loads(completed.stdout)
    return loaded


def suppressing_calls_in(source: str) -> list[str]:
    """Every call in ``source`` that would apply an off-plan suppression."""
    return sorted(
        name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (name := _called_name(node)) is not None
        and name in SUPPRESSING_CALLS
    )


def _called_name(call: ast.Call) -> str | None:
    """The name a call names, whether it is called bare or through a receiver."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def source_of(module: str) -> str:
    from importlib.util import find_spec

    spec = find_spec(module)
    assert spec is not None and spec.origin is not None, f"{module} has no source"
    return Path(spec.origin).read_text(encoding="utf-8")


def test_the_detection_reaches_no_off_plan_module_at_all() -> None:
    assert off_plan_modules_loaded_by(*DETECTION_MODULES) == [], (
        "conflict detection reached the off-plan package. A commitment during a declared span is "
        "still a commitment and a pinned block inside one is still the user's edit, so a "
        "suppression here would silence exactly the collision OP7 requires to be raised"
    )


def test_the_import_lens_can_see_an_off_plan_read() -> None:
    # The control. Without it, "the detection reaches no off-plan module" and "the probe cannot see
    # one" are indistinguishable, and the assertion above would pass forever.
    assert off_plan_modules_loaded_by(READS_OFF_PLAN) != []


@pytest.mark.parametrize("module", DETECTION_MODULES)
def test_no_detection_module_applies_a_suppression(module: str) -> None:
    assert suppressing_calls_in(source_of(module)) == []


def test_the_source_lens_can_see_a_suppression() -> None:
    # The second control, over the shape the import lens is blind to: `calendar_occupancy` imports
    # the suppression type for annotations only, so calling it loads no off-plan module.
    reached = "occupancy = calendar_occupancy(loaded, span=span, off_plan=suppression)"

    assert suppressing_calls_in(reached) == ["calendar_occupancy"]


def test_the_source_lens_reads_a_call_through_a_receiver_too() -> None:
    assert suppressing_calls_in("if off_plan.suppresses_content(inside):\n    pass") == [
        "suppresses_content"
    ]
