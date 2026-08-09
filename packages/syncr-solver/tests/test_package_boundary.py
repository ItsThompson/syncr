"""The solver package's import boundary.

The solver's purity is only possible because the API absorbs the I/O, so a solver
module importing persistence or the web stack is a design regression, not a style nit.

The walk runs in a SUBPROCESS because ``sys.modules`` is process-global: a sibling
test module importing a forbidden package would otherwise fail this test and blame
`syncr_solver`. The probe is duplicated in each member's boundary test rather than
shared, because a member's test path resolves against its own directory and reaching
into a sibling's test tree would be a worse coupling than twelve repeated lines.

**The child is told which tree to import, and it reports which one it did.** A subprocess
inherits none of the parent's ``sys.path``, so without being told it resolves this package
through the interpreter's editable install: the probe then walks a different checkout, and a
forbidden import added here would pass. Both the instruction and the assertion on it are
load-bearing, and the assertion is what makes the instruction impossible to drop silently.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import syncr_solver

PACKAGE = "syncr_solver"

# Where this suite's own interpreter imported the package from. The child is pointed here.
SOURCE_ROOT = Path(syncr_solver.__file__).resolve().parent.parent

FORBIDDEN_IMPORTS = frozenset(
    {
        "syncr_api",
        "syncr_learning",
        "sqlalchemy",
        "alembic",
        "fastapi",
        "starlette",
        "httpx",
        "scipy",
        "sklearn",
    }
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
        # ``PATH`` is carried through so the child can find an interpreter or a subprocess of its
        # own; nothing else of the ambient environment is, so a variable on the developer's machine
        # cannot change which tree gets measured.
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(SOURCE_ROOT)},
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

    assert walked.resolved == SOURCE_ROOT, (
        f"the probe walked {walked.resolved}, this test imported {SOURCE_ROOT}"
    )


def test_no_solver_module_reaches_for_io_or_an_ml_library() -> None:
    walked = import_every_module(PACKAGE)
    leaked = sorted(FORBIDDEN_IMPORTS & walked.loaded)

    assert walked.imported, f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"
