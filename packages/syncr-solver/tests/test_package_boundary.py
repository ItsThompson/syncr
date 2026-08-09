"""The solver package's import boundary.

The solver's purity is only possible because the API absorbs the I/O, so a solver
module importing persistence or the web stack is a design regression, not a style nit.

The walk runs in a SUBPROCESS because ``sys.modules`` is process-global: a sibling
test module importing a forbidden package would otherwise fail this test and blame
`syncr_solver`. The probe is duplicated in each member's boundary test rather than
shared, because a member's test path resolves against its own directory and reaching
into a sibling's test tree would be a worse coupling than repeating the probe in each.

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

import pytest

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


@pytest.fixture(scope="module")
def walked() -> Walked:
    """One walk of this tree: the package is imported in a subprocess once for the whole module."""
    return import_every_module(PACKAGE)


def test_the_probe_walks_the_tree_this_test_imported(walked: Walked) -> None:
    # The instrument's own precondition. A child resolving the package through the interpreter's
    # editable install walks another checkout, and every forbidden import added here would pass.
    assert walked.resolved == SOURCE_ROOT, (
        f"the probe walked {walked.resolved}, this test imported {SOURCE_ROOT}"
    )


def test_no_solver_module_reaches_for_io_or_an_ml_library(walked: Walked) -> None:
    leaked = sorted(FORBIDDEN_IMPORTS & walked.loaded)

    assert walked.imported, f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"


def test_the_probe_ignores_a_pythonpath_from_the_ambient_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A child that inherits the environment measures whatever a developer's shell points at, and a
    # PYTHONPATH entry outranks the editable install. Unlike the comparison above, this holds in a
    # single checkout, where the parent's tree and the editable install are one path.
    (tmp_path / PACKAGE).mkdir()
    (tmp_path / PACKAGE / "__init__.py").write_text(
        '"""a tree nobody chose."""\n', encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    probed = import_every_module(PACKAGE)

    assert probed.resolved == SOURCE_ROOT, (
        f"the probe walked {probed.resolved}, this test imported {SOURCE_ROOT}"
    )
