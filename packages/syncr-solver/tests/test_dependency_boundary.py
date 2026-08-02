"""The zero-ML dependency boundary, read from the committed lockfile.

`syncr-solver` consuming a `WeightSet` of plain floats is what keeps scipy out of
the API image, keeps the solver deterministic and testable against hand-written
weight fixtures, and makes `syncr-learning` replaceable without touching the
request path. An import-time check cannot express that rule, because dev and CI
resolve one shared environment where any member's dependency is importable from
every member. The lockfile is where the rule is actually decidable.

This walks the runtime closure only: a lockfile's dev groups live under
`package.metadata.requires-dev` and never ship in an image. Optional-dependency
groups are folded in whether or not the extra was requested, which
over-approximates the closure: a "must not contain" assertion is safe in that
direction.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

LOCKFILE = Path(__file__).resolve().parents[3] / "uv.lock"

# scipy and scikit-learn are the two the spec names. The rest are here so a future
# "just one small model" import is caught by the same gate. numpy is deliberately
# absent: it is not an ML library, and forbidding it would be stricter than the
# rule the API image actually needs.
ML_PACKAGES = frozenset(
    {
        "scipy",
        "scikit-learn",
        "torch",
        "tensorflow",
        "xgboost",
        "lightgbm",
        "statsmodels",
    }
)


def _locked_packages() -> dict[str, dict[str, Any]]:
    lock: dict[str, Any] = tomllib.loads(LOCKFILE.read_text(encoding="utf-8"))
    return {package["name"]: package for package in lock["package"]}


def _direct_dependencies(package: dict[str, Any]) -> list[str]:
    names = [entry["name"] for entry in package.get("dependencies", [])]
    for extra in package.get("optional-dependencies", {}).values():
        names.extend(entry["name"] for entry in extra)
    return names


def runtime_closure(root: str) -> set[str]:
    """Every package that ships when ``root`` is installed from the lockfile."""
    packages = _locked_packages()
    assert root in packages, f"{root} is not a locked package"

    seen: set[str] = set()
    pending = [root]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(_direct_dependencies(packages[name]))
    return seen - {root}


@pytest.mark.parametrize("member", ["syncr-solver", "syncr-api", "syncr-common", "syncr-domain"])
def test_no_ml_library_ships_with_the_request_path(member: str) -> None:
    leaked = sorted(ML_PACKAGES & runtime_closure(member))

    assert leaked == [], f"{member} must ship no ML library, found {leaked}"


def test_the_solver_depends_on_the_domain() -> None:
    assert "syncr-domain" in runtime_closure("syncr-solver")


def test_the_domain_does_not_depend_on_the_solver() -> None:
    # The arrow runs common -> domain -> solver -> api. A reversal here would make
    # the pure package impure by transitivity.
    closure = runtime_closure("syncr-domain")

    assert "syncr-solver" not in closure
    assert "syncr-api" not in closure


def test_the_api_ships_the_solver_the_domain_and_common() -> None:
    closure = runtime_closure("syncr-api")

    assert {"syncr-common", "syncr-domain", "syncr-solver"} <= closure


def test_common_carries_no_workspace_dependency() -> None:
    # syncr-common is infra with no domain knowledge, so nothing in the workspace
    # is below it.
    closure = runtime_closure("syncr-common")

    assert not {name for name in closure if name.startswith("syncr-")}
