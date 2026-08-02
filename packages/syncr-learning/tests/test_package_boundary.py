"""The learning package's import boundary.

The learning job reads stored outcomes and writes a weight-set row. It is never on
the request path, so it carries no web stack, and it must not reach into the API
package or the solver.

The walk runs in a SUBPROCESS because ``sys.modules`` is process-global: a sibling
test module importing a forbidden package would otherwise fail this test and blame
`syncr_learning`. The probe is duplicated in each member's boundary test rather than
shared, because a member's test path resolves against its own directory and reaching
into a sibling's test tree would be a worse coupling than twelve repeated lines.
"""

from __future__ import annotations

import json
import subprocess
import sys

PACKAGE = "syncr_learning"

FORBIDDEN_IMPORTS = frozenset({"syncr_api", "syncr_solver", "fastapi", "starlette", "uvicorn"})

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
        check=True,
    )
    payload = json.loads(completed.stdout)
    return payload["imported"], {name.split(".", 1)[0] for name in payload["loaded"]}


def test_no_learning_module_reaches_for_the_web_stack_or_the_request_path() -> None:
    imported, loaded = import_every_module(PACKAGE)
    leaked = sorted(FORBIDDEN_IMPORTS & loaded)

    assert imported, f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"
