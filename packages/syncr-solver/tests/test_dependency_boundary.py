"""The zero-ML dependency boundary, read from the committed lockfile.

`syncr-solver` consuming a `WeightSet` of plain floats is what keeps scipy out of
the API image, keeps the solver deterministic and testable against hand-written
weight fixtures, and makes `syncr-learning` replaceable without touching the
request path. An import-time check cannot express that rule, because dev and CI
resolve one shared environment where any member's dependency is importable from
every member. The lockfile is where the rule is actually decidable.

This walks the runtime closure only: a lockfile's dev groups live under
`package.metadata.requires-dev` and never ship in an image. Extras are followed only
when a requirement in the closure actually asks for one, so the closure matches what
`uv export --package <member>` installs rather than an over-approximation of it.
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

# The offline learning job is a scheduled one-shot with no HTTP surface.
WEB_STACK_PACKAGES = frozenset({"fastapi", "starlette", "uvicorn"})

# One node of the resolution walk: a package plus the extras a requirement asked for.
type Requirement = tuple[str, tuple[str, ...]]


def _locked_packages() -> dict[str, dict[str, Any]]:
    lock: dict[str, Any] = tomllib.loads(LOCKFILE.read_text(encoding="utf-8"))
    return {package["name"]: package for package in lock["package"]}


def _requirements(entries: list[dict[str, Any]]) -> list[Requirement]:
    return [(entry["name"], tuple(entry.get("extra", ()))) for entry in entries]


def _direct_requirements(package: dict[str, Any], extras: tuple[str, ...]) -> list[Requirement]:
    optional: dict[str, list[dict[str, Any]]] = package.get("optional-dependencies", {})
    required = _requirements(package.get("dependencies", []))
    for extra in extras:
        required.extend(_requirements(optional.get(extra, [])))
    return required


def runtime_closure(root: str, extras: tuple[str, ...] = ()) -> set[str]:
    """Every package that ships when ``root`` is installed from the lockfile."""
    packages = _locked_packages()
    assert root in packages, f"{root} is not a locked package"

    seen: set[Requirement] = set()
    pending: list[Requirement] = [(root, extras)]
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(_direct_requirements(packages[node[0]], node[1]))
    return {name for name, _ in seen} - {root}


def api_closure() -> set[str]:
    """What the api image installs: the member plus the extras it declares."""
    return runtime_closure("syncr-api")


@pytest.mark.parametrize("member", ["syncr-solver", "syncr-api", "syncr-common", "syncr-domain"])
def test_no_ml_library_ships_with_the_request_path(member: str) -> None:
    leaked = sorted(ML_PACKAGES & runtime_closure(member))

    assert leaked == [], f"{member} must ship no ML library, found {leaked}"


def test_the_learning_image_carries_no_web_stack() -> None:
    # syncr-common's fastapi dependency sits behind an `http` extra that the
    # learning member does not request, so a one-shot job installs no server.
    leaked = sorted(WEB_STACK_PACKAGES & runtime_closure("syncr-learning"))

    assert leaked == [], f"syncr-learning must ship no web stack, found {leaked}"


def test_the_api_image_carries_the_web_stack_it_serves() -> None:
    # The mirror of the test above: the extra is requested here, so a missing
    # fastapi would be a packaging break rather than a boundary win.
    assert WEB_STACK_PACKAGES <= api_closure()


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
