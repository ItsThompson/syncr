"""The solver package's import boundary.

The solver's purity is only possible because the API absorbs the I/O, so a solver
module importing persistence or the web stack is a design regression, not a style
nit. The check imports every module in the package and then looks at what that
made importable, so it keeps holding as modules land.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import syncr_solver

FORBIDDEN_IMPORTS = (
    "syncr_api",
    "syncr_learning",
    "sqlalchemy",
    "alembic",
    "fastapi",
    "starlette",
    "httpx",
    "scipy",
    "sklearn",
)


def _import_every_module() -> list[str]:
    names = [syncr_solver.__name__]
    for module in pkgutil.walk_packages(syncr_solver.__path__, f"{syncr_solver.__name__}."):
        importlib.import_module(module.name)
        names.append(module.name)
    return names


def test_no_solver_module_reaches_for_io_or_an_ml_library() -> None:
    imported = _import_every_module()
    leaked = [name for name in FORBIDDEN_IMPORTS if name in sys.modules]

    assert imported, "expected at least the package itself to import"
    assert leaked == [], f"syncr_solver must not import {leaked}"
