"""The learning package's import boundary.

The learning job reads stored outcomes and writes a weight-set row. It is never on
the request path, so it carries no web stack, and it must not reach into the API
package or the solver.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import syncr_learning

FORBIDDEN_IMPORTS = (
    "syncr_api",
    "syncr_solver",
    "fastapi",
    "starlette",
    "uvicorn",
)


def _import_every_module() -> list[str]:
    names = [syncr_learning.__name__]
    for module in pkgutil.walk_packages(syncr_learning.__path__, f"{syncr_learning.__name__}."):
        importlib.import_module(module.name)
        names.append(module.name)
    return names


def test_no_learning_module_reaches_for_the_web_stack_or_the_request_path() -> None:
    imported = _import_every_module()
    leaked = [name for name in FORBIDDEN_IMPORTS if name in sys.modules]

    assert imported, "expected at least the package itself to import"
    assert leaked == [], f"syncr_learning must not import {leaked}"
