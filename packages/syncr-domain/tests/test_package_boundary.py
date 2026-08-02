"""The domain package's purity boundary.

`syncr-domain` is pure: entities, invariants, and arithmetic, with no I/O. That
purity is what lets the solver be tested with literals, so it is asserted rather
than trusted. The check imports every module in the package and then looks at what
that made importable, so it keeps holding as modules land.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import syncr_domain

# A domain module importing any of these would either invert the dependency
# direction (common -> domain -> solver -> api) or put I/O in a pure package.
FORBIDDEN_IMPORTS = (
    "syncr_api",
    "syncr_solver",
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
    names = [syncr_domain.__name__]
    for module in pkgutil.walk_packages(syncr_domain.__path__, f"{syncr_domain.__name__}."):
        importlib.import_module(module.name)
        names.append(module.name)
    return names


def test_no_domain_module_reaches_for_io_or_a_downstream_package() -> None:
    imported = _import_every_module()
    leaked = [name for name in FORBIDDEN_IMPORTS if name in sys.modules]

    assert imported, "expected at least the package itself to import"
    assert leaked == [], f"syncr_domain must not import {leaked}"
