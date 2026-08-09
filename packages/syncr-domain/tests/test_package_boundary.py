"""The domain package's purity boundary.

`syncr-domain` is pure: entities, invariants, and arithmetic, with no I/O and no
clock. That purity is what lets the solver be tested with literals, so it is asserted
rather than trusted. This suite polices every module under `src/syncr_domain`,
including ones other tickets add, and nothing needs registering for it to see them.

Two walks, because neither sees what the other does.

The **import walk** imports every module in a SUBPROCESS and reads `sys.modules`, so a
forbidden package reached transitively through a new dependency is caught even when no
source file names it. The subprocess matters because `sys.modules` is process-global: a
sibling test module importing a forbidden package would otherwise fail this test and
blame `syncr_domain`. The probe is duplicated in each member's boundary test rather
than shared, because a member's test path resolves against its own directory and
reaching into a sibling's test tree would be a worse coupling than twelve repeated
lines.

**The probe is told which tree to read, and it says which tree it read.** A subprocess
inherits none of the parent's `sys.path`, and pytest's `pythonpath` setting does not reach
it, so a child left to itself resolves `syncr_domain` through the venv's editable install
and walks whichever checkout that points at. In the main checkout that is this tree, so an
untold probe reads green while measuring a tree nobody chose. The child is therefore given
the source root this suite imported and prints `__file__` before it walks anything, and no
figure from the walk is believed until that path matches.

The **source walk** parses each module instead, because the import walk cannot see
either of the things it looks for. A clock read leaves no trace in `sys.modules`, since
`datetime` is imported by every module here for its types, and `os` and `pathlib` are
loaded by the interpreter itself long before this package is imported, so an
`open()` call is invisible there too. The source walk resolves import aliases before
matching, so `from datetime import datetime as dt; dt.now()` is caught as well as
`datetime.datetime.now()`.

`FORBIDDEN_ATTRIBUTES` matches a call's final attribute whatever its receiver, because no
alias can resolve a method on a value held in a local. That is deliberately blunt: a
future domain method named `today()` fails this walk. When it does, rename the method, or
add it to a narrow allowlist here with the reason. Do not widen the receiver rule, which
is what makes `path.read_text()` visible at all.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import syncr_domain

PACKAGE = "syncr_domain"

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src" / PACKAGE

# Where this suite's own interpreter imported the package from. A separate derivation from
# SOURCE_ROOT: that one is this worktree's layout, this one is whatever the running
# interpreter resolved, and they agree only when the suite is measuring its own tree.
IMPORTED_ROOT = Path(syncr_domain.__file__).resolve().parent

FIXTURES_MODULE = f"{PACKAGE}.fixtures"

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

# Standard-library I/O and unseeded randomness, named in source because the import walk
# cannot see them: the interpreter loads several of these itself, so `sys.modules` says
# nothing. Randomness belongs here for the same reason a clock does. A domain function's
# output must follow from its inputs, and the solver's determinism rests on it.
FORBIDDEN_SOURCE_IMPORTS = frozenset(
    {
        "os",
        "io",
        "pathlib",
        "shutil",
        "tempfile",
        "glob",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
        "http",
        "sqlite3",
        "random",
        "secrets",
    }
)

# A pure function is given its instants; it never asks what time it is, and it never mints
# a value from nowhere. Either would make a result depend on something other than the
# inputs, which is the one thing a property test cannot pin down. Matched on the fully
# qualified name, after alias resolution.
#
# `uuid.UUID` is not here and must not be: `identifiers.py` imports it as a type, and
# naming a type is not minting a value.
FORBIDDEN_CALLS = frozenset(
    {
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.datetime.fromtimestamp",
        "datetime.datetime.utcfromtimestamp",
        "datetime.date.today",
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
        "time.gmtime",
        "time.localtime",
        "uuid.uuid1",
        "uuid.uuid4",
        "open",
    }
)

# Calls whose receiver an import alias cannot resolve, such as a method on a value held
# in a local. Matched on the attribute alone, so the receiver does not matter.
#
# `time` is deliberately absent: `some_instant.time()` extracts wall time from a
# datetime, which is pure, and the qualified set above already covers `time.time`.
FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "now",
        "utcnow",
        "today",
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "uuid1",
        "uuid4",
        "open",
        "read_text",
        "write_text",
        "read_bytes",
        "write_bytes",
        "mkdir",
        "unlink",
    }
)

# The resolution is printed BEFORE the walk, so it stands on its own: a caller learns which
# tree was read even from a walk that then failed, and never the other way round.
_PROBE = """
import importlib, json, pkgutil, sys

package = importlib.import_module({package!r})
print(package.__file__)

names = [package.__name__]
for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
    importlib.import_module(module.name)
    names.append(module.name)

print(json.dumps({{"imported": names, "loaded": sorted(sys.modules)}}))
"""


@dataclass(frozen=True)
class Walked:
    """What the probe found: what it imported, what that loaded, and which tree it read."""

    imported: tuple[str, ...]
    loaded: frozenset[str]
    resolved: Path


def import_every_module(package: str) -> Walked:
    """Import every module in ``package`` in a fresh process pointed at this suite's tree.

    Reports no figure from another checkout: the child says where it resolved ``package``
    from, and that path is held against the one this suite imported before the walk is read
    at all.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", _PROBE.format(package=package)],
        capture_output=True,
        text=True,
        check=False,
        # ``PATH`` is carried through so the child can find an interpreter or a subprocess of its
        # own; nothing else of the ambient environment is, so a variable on the developer's machine
        # cannot change which tree gets measured.
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(IMPORTED_ROOT.parent)},
    )
    assert completed.returncode == 0, (
        f"the probe could not import {package}: {completed.stderr.strip()}"
    )
    resolution, _, walked = completed.stdout.partition("\n")
    resolved = Path(resolution.strip()).resolve().parent

    assert resolved == IMPORTED_ROOT, (
        f"the probe walked {resolved}, but this suite imported {package} from {IMPORTED_ROOT}"
    )
    payload = json.loads(walked)
    return Walked(
        imported=tuple(payload["imported"]),
        loaded=frozenset(name.split(".", 1)[0] for name in payload["loaded"]),
        resolved=resolved,
    )


def test_the_probe_walked_the_tree_in_this_worktree() -> None:
    """The other half of the resolution check. `import_every_module` holds the child against
    the tree this suite imported; this holds that tree against the one in this worktree, and
    only the two together make every figure below a statement about this checkout."""
    walked = import_every_module(PACKAGE)

    assert walked.resolved == SOURCE_ROOT, (
        f"the probe walked {walked.resolved}, which is not this worktree's {SOURCE_ROOT}"
    )


def test_no_domain_module_reaches_for_io_or_a_downstream_package() -> None:
    walked = import_every_module(PACKAGE)
    leaked = sorted(FORBIDDEN_IMPORTS & walked.loaded)

    assert walked.imported, f"expected at least {PACKAGE} itself to import"
    assert leaked == [], f"{PACKAGE} must not import {leaked}"


@dataclass(frozen=True)
class Scan:
    """What one module's source says it imports and calls.

    ``calls`` are fully qualified through the module's own import aliases.
    ``attributes`` is every call's final attribute, for a receiver no alias can resolve.
    """

    imports: frozenset[str]
    calls: frozenset[str]
    attributes: frozenset[str]


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Each locally bound name mapped to the qualified name it was imported as."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                bound[alias.asname or root] = alias.name if alias.asname else root
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                qualified = f"{module}.{alias.name}" if module else alias.name
                bound[alias.asname or alias.name] = qualified
    return bound


def _package_of(module: Path) -> str:
    """The dotted package a module's relative imports resolve against.

    ``zones.py`` resolves against ``syncr_domain``, ``fixtures/dst_weeks.py`` against
    ``syncr_domain.fixtures``.
    """
    parents = module.relative_to(SOURCE_ROOT).parent.parts
    return ".".join((PACKAGE, *parents))


def _resolve_relative(node: ast.ImportFrom, package: str) -> str:
    """The absolute package a relative import names.

    ``level`` counts dots: one is the module's own package, two its parent. Without
    this, ``from .fixtures.dst_weeks import ...`` records ``fixtures.dst_weeks``, which
    matches no rule stated in absolute terms.
    """
    parts = package.split(".")
    base = ".".join(parts[: len(parts) - (node.level - 1)])
    return f"{base}.{node.module}" if node.module else base


def _imported_modules(tree: ast.Module, package: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    modules.add(node.module)
                continue
            resolved = _resolve_relative(node, package)
            modules.add(resolved)
            # `from . import fixtures` names a submodule rather than a member, so the
            # imported names carry the module this rule is about.
            if node.module is None:
                modules.update(f"{resolved}.{alias.name}" for alias in node.names)
    return modules


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _qualified(dotted: str, aliases: dict[str, str]) -> str:
    head, _, rest = dotted.partition(".")
    resolved = aliases.get(head, head)
    return f"{resolved}.{rest}" if rest else resolved


def scan(source: Path, package: str = PACKAGE) -> Scan:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    aliases = _aliases(tree)
    called = [_dotted_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    return Scan(
        imports=frozenset(_imported_modules(tree, package)),
        calls=frozenset(_qualified(name, aliases) for name in called if name),
        attributes=frozenset(name.rsplit(".", 1)[-1] for name in called if name),
    )


def scan_every_module() -> dict[str, Scan]:
    modules = sorted(SOURCE_ROOT.rglob("*.py"))

    assert modules, f"expected source under {SOURCE_ROOT}"
    return {
        module.relative_to(SOURCE_ROOT).as_posix(): scan(module, _package_of(module))
        for module in modules
    }


def test_no_domain_module_reads_a_clock_a_file_or_a_random_value() -> None:
    found = {
        name: sorted(
            (scanned.calls & FORBIDDEN_CALLS) | (scanned.attributes & FORBIDDEN_ATTRIBUTES)
        )
        for name, scanned in scan_every_module().items()
    }

    assert {name: calls for name, calls in found.items() if calls} == {}, (
        f"every {PACKAGE} result follows from its inputs, so it reads none of these: {found}"
    )


def test_no_domain_module_imports_standard_library_io() -> None:
    found = {
        name: sorted(
            module
            for module in scanned.imports
            if module.split(".", 1)[0] in FORBIDDEN_SOURCE_IMPORTS
        )
        for name, scanned in scan_every_module().items()
    }

    assert {name: imports for name, imports in found.items() if imports} == {}, (
        f"{PACKAGE} performs no I/O, so it imports none: {found}"
    )


def test_no_runtime_module_imports_the_fixtures() -> None:
    """The fixtures ship in `src/` so other packages' suites can import them, which puts
    them in the wheel. Nothing but a test may read them, and that is the enforcement."""
    found = {
        name: sorted(module for module in scanned.imports if module.startswith(FIXTURES_MODULE))
        for name, scanned in scan_every_module().items()
        if not name.startswith("fixtures/")
    }

    assert {name: imports for name, imports in found.items() if imports} == {}, (
        f"{FIXTURES_MODULE} is test data, so no runtime module imports it: {found}"
    )


# One planted module per rule the source walk enforces, so every addition to a set above
# is known to be capable of failing. The first two are the alias cases a tail-matching
# walk misses.
EVASIONS = [
    ("an aliased datetime class", "from datetime import datetime as dt\nAT = dt.now(tz=None)\n"),
    ("an aliased time function", "from time import time as wall_clock\nAT = wall_clock()\n"),
    ("an aliased module", "import time as t\nAT = t.monotonic()\n"),
    ("a bare builtin", "DATA = open('/etc/hosts').read()\n"),
    ("a method on a local", "def load(path):\n    return path.read_text()\n"),
    ("a minted identifier", "import uuid\n\nID = uuid.uuid4()\n"),
    ("an aliased mint", "from uuid import uuid4 as fresh\n\nID = fresh()\n"),
]


@pytest.mark.parametrize(("evasion", "source"), EVASIONS)
def test_the_source_walk_catches_every_evasion(evasion: str, source: str, tmp_path: Path) -> None:
    planted = tmp_path / "impure.py"
    planted.write_text(source, encoding="utf-8")

    scanned = scan(planted)

    assert (scanned.calls & FORBIDDEN_CALLS) or (scanned.attributes & FORBIDDEN_ATTRIBUTES), (
        f"the source walk missed {evasion}"
    )


@pytest.mark.parametrize(
    ("planted_import", "expected"),
    [
        ("import socket\n", "socket"),
        ("from pathlib import Path\n", "pathlib"),
        ("import urllib.request\n", "urllib.request"),
        ("import secrets\n", "secrets"),
    ],
)
def test_the_import_rule_can_fail(planted_import: str, expected: str, tmp_path: Path) -> None:
    planted = tmp_path / "does_io.py"
    planted.write_text(planted_import, encoding="utf-8")

    assert expected in scan(planted).imports


def test_the_walk_allows_a_type_import_of_the_identifier_it_forbids_minting() -> None:
    """`identifiers.py` imports `uuid.UUID` as a type. Naming a type is not minting a
    value, so the rule must not read the two as the same thing."""
    scanned = scan_every_module()

    assert "identifiers.py" in scanned, "expected the identifier aliases to be scanned"
    assert not scanned["identifiers.py"].calls & FORBIDDEN_CALLS


# Six ways a runtime module can reach the fixtures. The three relative forms are the
# ones a walk reading `node.module` alone records under a name no absolute rule matches.
FIXTURE_IMPORTS = [
    f"from {FIXTURES_MODULE}.dst_weeks import FALL_BACK\n",
    f"from {FIXTURES_MODULE} import dst_weeks\n",
    f"import {FIXTURES_MODULE}.dst_weeks as data\n",
    "from .fixtures.dst_weeks import FALL_BACK\n",
    "from .fixtures import dst_weeks\n",
    "from . import fixtures\n",
]


@pytest.mark.parametrize("planted_import", FIXTURE_IMPORTS)
def test_the_fixtures_rule_catches_every_import_style(planted_import: str, tmp_path: Path) -> None:
    planted = tmp_path / "reads_a_fixture.py"
    planted.write_text(planted_import, encoding="utf-8")

    imported = scan(planted, PACKAGE).imports

    assert any(module.startswith(FIXTURES_MODULE) for module in imported), (
        f"a runtime module could import the fixtures as: {planted_import.strip()}"
    )


def test_a_relative_import_resolves_against_the_scanned_module_s_own_package() -> None:
    """The control on the resolution itself: a sibling import inside `fixtures/` must
    resolve to `syncr_domain.fixtures`, not to `syncr_domain`."""
    assert _package_of(SOURCE_ROOT / "zones.py") == PACKAGE
    assert _package_of(SOURCE_ROOT / "fixtures" / "dst_weeks.py") == FIXTURES_MODULE
