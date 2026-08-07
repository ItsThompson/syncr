"""The learning package's import boundary, and the closure the image installs.

The learning job reads stored outcomes and writes a weight-set row. It is never on
the request path, so it carries no web stack, and it must not reach into the API
package or the solver.

The walk runs in a SUBPROCESS because ``sys.modules`` is process-global: a sibling
test module importing a forbidden package would otherwise fail this test and blame
`syncr_learning`. The probe is duplicated in each member's boundary test rather than
shared, because a member's test path resolves against its own directory and reaching
into a sibling's test tree would be a worse coupling than twelve repeated lines.

**The probe reports the checkout it resolved, and this file asserts it is the one under
test.** The subprocess inherits no ``PYTHONPATH`` from pytest's own ``pythonpath``
setting, so it resolves ``syncr_learning`` through the venv's editable install rather
than through this tree. Today the two are one path; a probe that did not say which it
read could pass against another checkout entirely, which is a boundary test measuring
the wrong tree.

**Both forbidden workspace packages are DEV dependencies of this member**, because two
agreement tests need this package's restated spellings and their owners in one process.
That is why the runtime closure is asserted here as well as the imports: a dev dependency
the image excludes and an import no module makes are different claims, and the second does
not imply the first.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import syncr_learning

PACKAGE = "syncr_learning"

FORBIDDEN_IMPORTS = frozenset({"syncr_api", "syncr_solver", "fastapi", "starlette", "uvicorn"})

LOCKFILE = Path(__file__).resolve().parents[3] / "uv.lock"

_PROBE = """
import importlib, json, pkgutil, sys

package = importlib.import_module({package!r})
names = [package.__name__]
for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
    importlib.import_module(module.name)
    names.append(module.name)

print(json.dumps({{
    "imported": names,
    "loaded": sorted(sys.modules),
    "resolved": package.__file__,
}}))
"""


def import_every_module(package: str, *, cwd: Path | None = None) -> dict[str, Any]:
    """Import every module in ``package`` in a fresh process, and report what it resolved.

    Returns the modules imported, the top-level packages that ended up loaded, and the file the
    subprocess resolved the package from, so a caller can prove which checkout it measured.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", _PROBE.format(package=package)],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    assert completed.returncode == 0, (
        f"the probe could not import {package}: {completed.stderr.strip()}"
    )
    payload: dict[str, Any] = json.loads(completed.stdout)
    payload["loaded"] = {name.split(".", 1)[0] for name in payload["loaded"]}
    return payload


def test_the_probe_measured_the_checkout_this_suite_is_running_from() -> None:
    # Without this the walk below could pass against a package installed from somewhere else. The
    # subprocess does not inherit pytest's `pythonpath`, so the two resolutions are independent and
    # comparing them is what makes the boundary claim about THIS tree.
    probed = import_every_module(PACKAGE)

    assert Path(probed["resolved"]).resolve() == Path(syncr_learning.__file__).resolve()


def test_no_learning_module_reaches_for_the_web_stack_or_the_request_path() -> None:
    probed = import_every_module(PACKAGE)
    leaked = sorted(FORBIDDEN_IMPORTS & probed["loaded"])

    assert probed["imported"], f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"


def test_the_probe_would_see_a_forbidden_import(tmp_path: Path) -> None:
    # The positive control. A walk that reported nothing because it imported nothing would pass the
    # test above forever, so the probe is run against a package that DOES import a forbidden name.
    package = tmp_path / "probe_control"
    package.mkdir()
    (package / "__init__.py").write_text("import syncr_solver\n", encoding="utf-8")

    probed = import_every_module("probe_control", cwd=tmp_path)

    assert "syncr_solver" in probed["loaded"]


def locked_packages() -> dict[str, dict[str, Any]]:
    lock: dict[str, Any] = tomllib.loads(LOCKFILE.read_text(encoding="utf-8"))
    return {package["name"]: package for package in lock["package"]}


def runtime_closure(root: str) -> set[str]:
    """Every package that ships when ``root`` is installed from the lockfile.

    Runtime only: a lockfile's dev groups live under ``package.metadata.requires-dev`` and never
    ship
    in an image, which is the distinction this member's two workspace dev dependencies rest on.
    """
    packages = locked_packages()
    assert root in packages, f"{root} is not a locked package"
    seen: set[str] = set()
    pending = [root]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(one["name"] for one in packages[name].get("dependencies", []))
    return seen - {root}


def test_the_learning_image_carries_the_ml_libraries_this_member_alone_may_have() -> None:
    # The positive control for the solver's own "no ML anywhere else" gate: that test proves four
    # members do not ship scipy, and this proves the same walk can see it where it IS.
    assert {"scipy", "scikit-learn"} <= runtime_closure("syncr-learning")


@pytest.mark.parametrize("forbidden", ["syncr-api", "syncr-solver"])
def test_the_image_installs_neither_workspace_dev_dependency(forbidden: str) -> None:
    # They exist so two agreement tests can hold this package's restated spellings against their
    # owners in one process. A runtime dependency on either would put fastapi in a one-shot job and
    # would make the import boundary above unenforceable.
    assert forbidden not in runtime_closure("syncr-learning")


def test_the_two_dev_dependencies_are_declared_rather_than_borrowed() -> None:
    # The agreement tests import them, so they are a real dependency of this member's suite. Left
    # undeclared they would work only because the workspace resolves one shared venv, and a member
    # installed alone would fail to collect.
    manifest = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    declared = {one.split(">")[0].split("=")[0] for one in manifest["dependency-groups"]["dev"]}

    assert {"syncr-api", "syncr-solver"} <= declared
