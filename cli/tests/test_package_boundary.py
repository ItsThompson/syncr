"""The CLI package's import boundary.

The CLI is an OAuth client of the API, not a second copy of it: it reaches the
product over HTTP and must never import the server-side package.

``syncr_solver`` is forbidden for a second reason, and it is the AI boundary rather
than the deployment one: **this CLI never computes a schedule.** Placement lives
behind the API, so a CLI that could import the solver could grow a local one, and
the property that identical inputs produce identical plans would stop being a
property of one component.

``syncr_domain`` is deliberately absent from the forbidden set. It is pure --
entities, interval arithmetic, and the product's one rendering of a duration -- and
this package reads from it rather than spelling either a second time.

The walk runs in a SUBPROCESS because ``sys.modules`` is process-global: a sibling
test module importing a forbidden package would otherwise fail this test and blame
`syncr_cli`. The probe is duplicated in each member's boundary test rather than
shared, because a member's test path resolves against its own directory and reaching
into a sibling's test tree would be a worse coupling than twelve repeated lines.

**The child is told which tree to import, and it reports which one it did.** A
subprocess inherits none of the parent's ``sys.path``, so without being told it
resolves this package through the interpreter's editable install: the probe then
reads a different checkout, and a forbidden import added here would pass. Both the
instruction and the assertion on it are load-bearing, and the assertion is what
makes the instruction impossible to drop silently. The environment is
``tests/child.py``'s, shared with this suite's other two launch sites.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from tests.child import SOURCE_ROOT, child_environment

PACKAGE = "syncr_cli"

FORBIDDEN_IMPORTS = frozenset(
    {"syncr_api", "syncr_learning", "syncr_solver", "sqlalchemy", "alembic", "fastapi"}
)

_PROBE = """
import importlib, json, pathlib, pkgutil, sys

package = importlib.import_module({package!r})
names = [package.__name__]
for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
    importlib.import_module(module.name)
    names.append(module.name)

print(json.dumps({{
    "imported": names,
    "loaded": sorted(sys.modules),
    "resolved": str(pathlib.Path(package.__file__).resolve().parent.parent),
}}))
"""


class Walked(NamedTuple):
    """What the probe found: what it imported, what that loaded, and which tree it read."""

    imported: list[str]
    loaded: set[str]
    resolved: Path


def import_every_module(package: str) -> Walked:
    """Import every module in ``package`` in a fresh process, pointed at this tree."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", _PROBE.format(package=package)],
        capture_output=True,
        text=True,
        check=False,
        env=child_environment(),
    )
    assert completed.returncode == 0, (
        f"the probe could not import {package}: {completed.stderr.strip()}"
    )
    payload = json.loads(completed.stdout)
    return Walked(
        imported=payload["imported"],
        loaded={name.split(".", 1)[0] for name in payload["loaded"]},
        resolved=Path(payload["resolved"]),
    )


def test_the_probe_walks_the_tree_this_test_imported() -> None:
    # The instrument's own precondition. A child resolving the package through the interpreter's
    # editable install walks another checkout, and every forbidden import added here would pass.
    walked = import_every_module(PACKAGE)

    assert walked.resolved == SOURCE_ROOT


def test_the_cli_does_not_import_the_server_side_package() -> None:
    walked = import_every_module(PACKAGE)
    leaked = sorted(FORBIDDEN_IMPORTS & walked.loaded)

    assert walked.imported, f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"


def test_the_solver_is_in_the_forbidden_set() -> None:
    # The import walk above cannot notice this member leaving the set while no module imports the
    # solver, so removing it would be a silent widening of the boundary. This is the guard on the
    # set; the walk is the guard on the code.
    assert "syncr_solver" in FORBIDDEN_IMPORTS
    assert "syncr_domain" not in FORBIDDEN_IMPORTS
