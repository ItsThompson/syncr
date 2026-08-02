"""The domain package's purity boundary.

`syncr-domain` is pure: entities, invariants, and arithmetic, with no I/O and no
clock. That purity is what lets the solver be tested with literals, so it is asserted
rather than trusted.

The import walk runs in a SUBPROCESS because ``sys.modules`` is process-global: a
sibling test module importing a forbidden package would otherwise fail this test and
blame `syncr_domain`. Later waves add many modules to this suite. The probe is
duplicated in each member's boundary test rather than shared, because a member's test
path resolves against its own directory and reaching into a sibling's test tree would
be a worse coupling than twelve repeated lines.

The clock walk reads source instead, because an unread clock leaves no trace in
``sys.modules``: ``datetime`` is imported by every module here for its types.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

PACKAGE = "syncr_domain"

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src" / PACKAGE

# Importing any of these would either invert the dependency direction
# (common -> domain -> solver -> api) or put I/O in a pure package.
FORBIDDEN_IMPORTS = frozenset(
    {
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
    }
)

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


def test_no_domain_module_reaches_for_io_or_a_downstream_package() -> None:
    imported, loaded = import_every_module(PACKAGE)
    leaked = sorted(FORBIDDEN_IMPORTS & loaded)

    assert imported, f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"


# A pure function is given its instants; it never asks what time it is. Reading a
# clock here would make an arithmetic result depend on when the test ran, which is
# the one thing a property test cannot pin down. The pairs are matched on the tail of
# the dotted name, so `datetime.datetime.now()` is caught as well as `datetime.now()`.
CLOCK_READS = frozenset(
    {
        "datetime.now",
        "datetime.utcnow",
        "datetime.today",
        "date.today",
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
    }
)


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def clock_reads_in(source: Path) -> list[str]:
    calls = (
        _dotted_name(node.func)
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
    )
    return [call for call in calls if any(call.endswith(read) for read in CLOCK_READS)]


def test_no_domain_module_reads_a_clock() -> None:
    modules = sorted(SOURCE_ROOT.rglob("*.py"))

    found = {
        module.relative_to(SOURCE_ROOT).as_posix(): reads
        for module in modules
        if (reads := clock_reads_in(module))
    }

    assert modules, f"expected source under {SOURCE_ROOT}"
    assert found == {}, f"{PACKAGE} must be given its instants, not read them: {found}"


def test_the_clock_walk_can_fail(tmp_path: Path) -> None:
    """The control. A walk that finds nothing must be able to find something."""
    planted = tmp_path / "reads_a_clock.py"
    planted.write_text(
        "import datetime\n\nSTAMPED_AT = datetime.datetime.now(tz=datetime.UTC)\n",
        encoding="utf-8",
    )

    assert clock_reads_in(planted) == ["datetime.datetime.now"]
