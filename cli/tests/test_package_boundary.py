"""The CLI package's import boundary.

The CLI is an OAuth client of the API, not a second copy of it: it reaches the
product over HTTP and must never import the server-side package.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import syncr_cli

FORBIDDEN_IMPORTS = (
    "syncr_api",
    "syncr_learning",
    "sqlalchemy",
    "alembic",
    "fastapi",
)


def _import_every_module() -> list[str]:
    names = [syncr_cli.__name__]
    for module in pkgutil.walk_packages(syncr_cli.__path__, f"{syncr_cli.__name__}."):
        importlib.import_module(module.name)
        names.append(module.name)
    return names


def test_the_cli_does_not_import_the_server_side_package() -> None:
    imported = _import_every_module()
    leaked = [name for name in FORBIDDEN_IMPORTS if name in sys.modules]

    assert imported, "expected at least the package itself to import"
    assert leaked == [], f"syncr_cli must not import {leaked}"
