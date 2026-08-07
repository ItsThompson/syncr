"""Every table this application declares, discovered rather than listed.

``alembic/env.py`` imports seventeen ``models`` modules by hand, for the side effect of attaching
their tables to the shared metadata. A second hand-written copy of that list is a list that drifts:
the fingerprint would silently stop counting the table a new feature added, the drill would pass
without ever looking at it, and nothing would report the omission.

So the modules are found by walking the package. ``tests/test_recovery_fingerprint.py`` crosses the
walk against ``env.py``'s own imports in both directions, which makes the drift visible on the
autogenerate side too: a model module missing from ``env.py`` is a migration that will not be
generated.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from typing import TYPE_CHECKING, Final

import syncr_api
from syncr_api.core.orm import Base

if TYPE_CHECKING:
    from sqlalchemy import Table

# What a feature package calls the module its mapped classes live in.
MODELS_MODULE: Final = "models"


def model_modules() -> tuple[str, ...]:
    """Every ``syncr_api.<package>.models`` module that exists, in a stable order."""
    found = []
    for package in pkgutil.iter_modules(syncr_api.__path__):
        if not package.ispkg:
            continue
        candidate = f"{syncr_api.__name__}.{package.name}.{MODELS_MODULE}"
        if importlib.util.find_spec(candidate) is not None:
            found.append(candidate)
    return tuple(sorted(found))


def registered_tables() -> tuple[Table, ...]:
    """Every table the declarative metadata holds, with every model module imported first.

    Importing is the registration: a table attaches to the metadata when its class body executes, so
    a reading taken without these imports describes whichever packages the caller happened to touch.
    """
    for module in model_modules():
        importlib.import_module(module)
    return tuple(Base.metadata.sorted_tables)
