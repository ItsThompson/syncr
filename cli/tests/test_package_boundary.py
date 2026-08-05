"""The CLI package's import boundary.

The CLI is an OAuth client of the API, not a second copy of it: it reaches the
product over HTTP and must never import the server-side package.

``syncr_solver`` is forbidden for a second reason, and it is the AI boundary rather
than the deployment one: **this CLI never computes a schedule.** Placement lives
behind the API, so a CLI that could import the solver could grow a local one, and
the property that identical inputs produce identical plans would stop being a
property of one component.

``syncr_domain`` is deliberately absent from the forbidden set. It is pure --
entities, interval arithmetic, and the product's one rendering of a duration -- and
this package reads from it rather than spelling either a second time.

The walk runs in a SUBPROCESS because ``sys.modules`` is process-global: a sibling
test module importing a forbidden package would otherwise fail this test and blame
`syncr_cli`. The probe is duplicated in each member's boundary test rather than
shared, because a member's test path resolves against its own directory and reaching
into a sibling's test tree would be a worse coupling than twelve repeated lines.
"""

from __future__ import annotations

import json
import subprocess
import sys

PACKAGE = "syncr_cli"

FORBIDDEN_IMPORTS = frozenset({"syncr_api", "syncr_learning", "sqlalchemy", "alembic", "fastapi"})

_PROBE = """
import importlib, json, pkgutil, sys

package = importlib.import_module({package!r})
names = [package.__name__]
for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
    importlib.import_module(module.name)
    names.append(module.name)

print(json.dumps({{"imported": names, "loaded": sorted(sys.modules)}}))
"""


def import_every_module(package: str) -> tuple[list[str], set[str]]:
    """Import every module in ``package`` in a fresh process.

    Returns the modules imported and the top-level packages that ended up loaded.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", _PROBE.format(package=package)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"the probe could not import {package}: {completed.stderr.strip()}"
    )
    payload = json.loads(completed.stdout)
    return payload["imported"], {name.split(".", 1)[0] for name in payload["loaded"]}


def test_the_cli_does_not_import_the_server_side_package() -> None:
    imported, loaded = import_every_module(PACKAGE)
    leaked = sorted(FORBIDDEN_IMPORTS & loaded)

    assert imported, f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"
