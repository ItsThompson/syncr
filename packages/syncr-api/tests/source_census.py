"""Reading the repository's own source: the offset's readers, and the wall clock's.

Two claims about this tree are enforceable only by a test that reads the code as text. One
environment variable has exactly one reader, and one package reads the wall clock in exactly
one place, and both degrade silently as new code arrives: what is needed is not a test of
today's modules but a reading that examines whatever modules exist whenever it runs.

Every helper here returns data rather than asserting, so each claim can be checked against
the real tree AND against a deliberately planted second reader. A census with no positive
control passes forever once it has gone blind, which is worse than having no census at all,
and both readings here have gone blind twice and been widened twice.

THE ALIAS MECHANISM IS ONE FUNCTION, USED FOUR TIMES. :func:`imported_as` returns the local
names a source binds one imported object to, and the caller decides whether the object's own
name counts as well. That decision is the difference between finding `os.environ` however
`os` was imported, and mistaking `from datetime import time` for the wall clock: the first
seeds the canonical name, the second must not.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import syncr_api
from syncr_api.core import clock
from syncr_api.core.clock import CLOCK_OFFSET_ENV_VAR
from syncr_api.core.settings import EnvSettings
from tests.test_alert_rules import member_roots, repo_root

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# ---------------------------------------------------------------------------
# The trees a reading is taken over
# ---------------------------------------------------------------------------


def tracked_python_sources() -> tuple[Path, ...]:
    """Every Python file the index holds, which is the repository as it will be committed.

    Git answers what the files are, rather than a walk with a list of directories to skip:
    the index covers a file staged and not yet committed, it cannot see a scratch file or a
    generated tree, and it grows a new member without anyone remembering to add it here.
    """
    listed = subprocess.run(
        # `git` from the PATH the developer and CI both have.
        ["git", "ls-files", "--cached", "-z", "*.py"],  # noqa: S607
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    found = tuple(repo_root() / name for name in listed.stdout.split("\0") if name)
    assert found, "git listed no Python file, so every reading here would pass over nothing"
    return found


def api_sources() -> tuple[Path, ...]:
    """This package's own Python files, which are what the offset has to reach."""
    tree = repo_root() / member_roots()[syncr_api.__name__] / syncr_api.__name__
    found = tuple(sorted(tree.rglob("*.py")))
    assert found, f"no source found under {tree}"
    return found


def clock_module() -> Path:
    """The one file that is allowed to read the offset, resolved from the module itself."""
    return Path(clock.__file__).resolve()


def offset_constant_name() -> str:
    """The identifier the offset's name is bound to, read from the module rather than typed.

    A renamed constant would otherwise leave the readings below looking for a name nothing
    uses, which is a census that passes because it can no longer see anything.
    """
    bound = [
        name
        for name, value in vars(clock).items()
        if name.isupper() and value == CLOCK_OFFSET_ENV_VAR
    ]
    assert len(bound) == 1, f"the offset's name is bound {len(bound)} times in {clock.__name__}"
    return bound[0]


# ---------------------------------------------------------------------------
# Names, and the aliases a source reaches them by
# ---------------------------------------------------------------------------


def named(node: ast.expr) -> str | None:
    """The trailing name of an attribute or a bare name, and nothing for anything else."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def imported_as(tree: ast.Module, *, module: str, names: tuple[str, ...]) -> frozenset[str]:
    """The local names this source binds one module's objects to. Aliases only.

    The object's own name is NOT included, because whether it counts depends on the caller.
    An attribute access needs no entry at all: :func:`named` matches an attribute by its
    trailing name, so `os.environ` is found through `environ` however `os` was imported. A
    bare call is the opposite case: `from time import time` binds a wall clock and
    `from datetime import time` binds a time-of-day type, and only the module the name came
    from separates them.
    """
    return frozenset(
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
        if alias.name in names
    )


# ---------------------------------------------------------------------------
# Who reads the environment for the offset
# ---------------------------------------------------------------------------

# How a Python source reads the process environment. Keyed on the mapping the read goes
# through, so `settings["DATABASE_URL"]` on something that is not the environment does not
# read as one.
ENVIRONMENT_MODULE = "os"
ENVIRONMENT_MAPPINGS = ("environ", "environb")
GETENV_FUNCTIONS = ("getenv", "getenvb")

# The mapping methods that RETURN the value at a key, so each of them is a read. `pop` and
# `setdefault` also mutate, which is why they are easy to overlook and no less a read.
READ_METHODS = ("get", "setdefault", "pop")

# The two calls that turn one spelling of a name into the other. `os.environb` is keyed by
# bytes, so `CLOCK_OFFSET_ENV_VAR.encode()` is the only way a working module reads it through
# the constant: the same constant, one method call away.
TRANSCODINGS = ("encode", "decode")


def environment_names(tree: ast.Module) -> frozenset[str]:
    return frozenset(ENVIRONMENT_MAPPINGS) | imported_as(
        tree, module=ENVIRONMENT_MODULE, names=ENVIRONMENT_MAPPINGS
    )


def is_the_environment(node: ast.expr, environment: frozenset[str]) -> bool:
    """Whether an expression is the process environment, or a copy or a merge of one.

    A copy reads the same value, and Python spells one four ways beyond the mapping itself: a
    call taking it (`dict(os.environ)`), a method on it (`os.environ.copy()`), an unpack
    (`{**os.environ}`), and a merge (`os.environ | {}`). Each case recurses, so a copy of a
    copy is a copy, and an assignment expression is looked through to the value it binds.
    """
    if named(node) in environment:
        return True
    if isinstance(node, ast.NamedExpr):
        return is_the_environment(node.value, environment)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and is_the_environment(
            node.func.value, environment
        ):
            return True
        passed = [*node.args, *(keyword.value for keyword in node.keywords)]
        return any(is_the_environment(argument, environment) for argument in passed)
    if isinstance(node, ast.Dict):
        return any(
            key is None and is_the_environment(value, environment)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return is_the_environment(node.left, environment) or is_the_environment(
            node.right, environment
        )
    return False


def environment_keys(tree: ast.Module) -> Iterator[ast.expr]:
    """Every key expression a source reads the process environment with."""
    environment = environment_names(tree)
    getenvs = frozenset(GETENV_FUNCTIONS) | imported_as(
        tree, module=ENVIRONMENT_MODULE, names=GETENV_FUNCTIONS
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and is_the_environment(node.value, environment):
            yield node.slice
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        if named(function) in getenvs or (
            isinstance(function, ast.Attribute)
            and function.attr in READ_METHODS
            and is_the_environment(function.value, environment)
        ):
            yield node.args[0]


def keys_the_offset(key: ast.expr, offsets: frozenset[str]) -> bool:
    """Whether one environment read is keyed to the offset, by literal or by a bound name.

    Both spellings of the name count, and a transcoding call is looked through, because the
    byte-keyed mapping is in this reading's own vocabulary and a `str` key would raise there.
    """
    if isinstance(key, ast.Call) and named(key.func) in TRANSCODINGS:
        return isinstance(key.func, ast.Attribute) and keys_the_offset(key.func.value, offsets)
    if isinstance(key, ast.Constant):
        return key.value in (CLOCK_OFFSET_ENV_VAR, CLOCK_OFFSET_ENV_VAR.encode())
    return named(key) in offsets


def reads_the_offset(tree: ast.Module) -> bool:
    """Whether a source reads the process environment for the offset.

    Keyed by either literal or by any local name the file itself binds the offset's constant
    to, its own name included, so a module-qualified `clock.CLOCK_OFFSET_ENV_VAR` needs no
    alias. Assuming the constant arrives under its own name alone is how a census comes to be
    blind to one `as` clause.
    """
    constant = offset_constant_name()
    offsets = frozenset({constant}) | imported_as(tree, module=clock.__name__, names=(constant,))
    return any(keys_the_offset(key, offsets) for key in environment_keys(tree))


# ---------------------------------------------------------------------------
# Who reads the wall clock
# ---------------------------------------------------------------------------

# The owners a wall-clock read goes through, and the calls on one that return the current
# instant. Keyed on a resolved owner, so `settings.now()` on something that is not a clock
# does not read as one.
WALL_CLOCK_MODULE = "datetime"
WALL_CLOCK_OWNERS = ("datetime", "date", "time")
WALL_CLOCK_CALLS = ("now", "utcnow", "today", "time", "time_ns")

# The wall-clock readers that are functions in their own right, so a source can import one and
# call it with no owner in front of it. `from time import time` then `time()` is ordinary
# Python, needs no alias to hide, and `ruff`'s DTZ rules do not flag it.
#
# THE CANONICAL NAMES ARE NOT SEEDED HERE, because `from datetime import time` imports the
# time-of-day TYPE and `time(7, 0)` constructs a value rather than reading a clock. Five
# modules of this package do exactly that, so a reading that took the name alone would report
# five wall-clock readers that are not.
BARE_WALL_CLOCK_MODULE = "time"
BARE_WALL_CLOCK_READERS = ("time", "time_ns")


def wall_clock_names(tree: ast.Module) -> tuple[frozenset[str], frozenset[str]]:
    """Local names for a clock owner, and for a bare wall-clock function.

    Three ways such a name arrives, all resolved from the file's own nodes: the object's own
    name, an ``as`` alias on its import, and a local bound to it by assignment
    (`_clock = datetime.datetime`). The owner set is built while walking, so an assignment
    chain of any depth is followed as long as it appears in source order, which is the only
    order that runs.
    """
    owners = set(WALL_CLOCK_OWNERS) | imported_as(
        tree, module=WALL_CLOCK_MODULE, names=WALL_CLOCK_OWNERS
    )
    bare = imported_as(tree, module=BARE_WALL_CLOCK_MODULE, names=BARE_WALL_CLOCK_READERS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and named(node.value) in owners:
            owners.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return frozenset(owners), frozenset(bare)


def reads_the_wall_clock(tree: ast.Module) -> bool:
    owners, bare = wall_clock_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute):
            if named(function.value) in owners and function.attr in WALL_CLOCK_CALLS:
                return True
        elif isinstance(function, ast.Name) and function.id in bare:
            return True
    return False


# ---------------------------------------------------------------------------
# Where the refusal lands
# ---------------------------------------------------------------------------

# The one entrypoint of this package that is not a console script. Alembic's own convention
# names this file, so there is nothing to derive it from.
MIGRATION_ENTRYPOINT = "alembic/env.py"


def declared_entrypoints() -> Mapping[str, Path]:
    """Every entrypoint of this package, mapped to the file it runs, derived from the build.

    The console scripts come from ``[project.scripts]``, which is the list the installed image
    invokes, so a script added without reaching settings construction is visible here rather
    than needing anyone to remember it. No count is stated: the point is the property, and a
    count of entrypoints rots the next time one lands.
    """
    member = repo_root() / member_roots()[syncr_api.__name__]
    manifest = (member.parent / "pyproject.toml").read_text(encoding="utf-8")
    _, _, region = manifest.partition("[project.scripts]")
    declared, _, _ = region.partition("\n[")
    found = {}
    for line in declared.splitlines():
        target = line.partition("=")[2].strip().strip('"')
        if not target:
            continue
        module, _, _ = target.partition(":")
        found[target] = member / (module.replace(".", "/") + ".py")
    found[MIGRATION_ENTRYPOINT] = member.parent / MIGRATION_ENTRYPOINT
    assert len(found) > 1, "no entrypoint was derived, so the reading below covers nothing"
    return found


def settings_constructors() -> frozenset[str]:
    """Every name in this package whose call builds the settings the refusal lives in.

    Derived to a fixed point rather than listed, so an entrypoint reaching settings through a
    new helper is covered without an edit, and a helper that stops constructing them reddens.
    """
    built = {EnvSettings.__name__}
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in api_sources()]
    growing = True
    while growing:
        growing = False
        for tree in trees:
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef) or node.name in built:
                    continue
                if any(
                    isinstance(call, ast.Call) and named(call.func) in built
                    for call in ast.walk(node)
                ):
                    built.add(node.name)
                    growing = True
    return frozenset(built)


# ---------------------------------------------------------------------------
# The spellings the controls plant
# ---------------------------------------------------------------------------

# Every spelling a second reader of the offset could arrive as. The list is what the reading
# has been widened to see across three rounds: a copy taken with `dict()`, a copy taken any
# other way, the two read methods that also mutate, the merge forms, and the byte-keyed
# mapping the reading's own vocabulary names.
SECOND_READER_SPELLINGS = (
    'os.environ["{literal}"]',
    "os.environ.get({constant})",
    "os.environ.setdefault({constant}, '')",
    "os.environ.pop({constant}, '')",
    "os.getenv({constant}, '')",
    "dict(os.environ)[{constant}]",
    "dict(os.environ).get({constant})",
    "dict(**os.environ)[{constant}]",
    "os.environ.copy()[{constant}]",
    "os.environ.copy().copy()[{constant}]",
    "os.environ.copy().get({constant})",
    "{{**os.environ}}[{constant}]",
    "(os.environ | {{}})[{constant}]",
    "({{}} | os.environ)[{constant}]",
    "(_copy := dict(os.environ))[{constant}]",
    "os.environb[{constant}.encode()]",
    "os.getenvb({constant}.encode())",
)

# Every spelling a second wall-clock reader could arrive as. Four hid from the reading while it
# required the owner to be named literally, and `from time import time` needs no alias at all.
SECOND_CLOCK_SPELLINGS = (
    "from datetime import UTC, datetime\nread = datetime.now(UTC)",
    "from datetime import UTC, datetime as _dt\nread = _dt.now(UTC)",
    "from datetime import UTC, date\nread = date.today()",
    "import time\nread = time.time()",
    "from time import time\nread = time()",
    "from time import time as _wall\nread = _wall()",
    "from time import time_ns\nread = time_ns()",
    "import datetime as _d\n_clock = _d.datetime\nread = _clock.now(_d.UTC)",
    "import datetime as _d\n_a = _d.datetime\n_b = _a\nread = _b.now(_d.UTC)",
)

# Calls the wall-clock reading must NOT read as a clock. The first is not hypothetical: the
# widening that found the four spellings above reported five modules of this package until the
# bare form was keyed to the module it comes from.
INNOCENT_CALL_SPELLINGS = (
    "from datetime import time\nDAY_START = time(7, 0)",
    "read = settings.now()",
    "read = window.today()",
    "from datetime import timedelta\nread = timedelta(days=1)",
    "import time\nread = time.monotonic()",
)


def second_reader_source(spelling: str, alias: str | None) -> str:
    """One planted second reader, with the offset's constant under its own name or an alias.

    The read sits inside a function, so a spelling that would raise at import cannot fail a
    census for a reason that is not the census. Both readings walk every node whatever scope it
    is in, so nothing about the shapes changes.
    """
    constant = offset_constant_name()
    imported = f"from {clock.__name__} import {constant}"
    read = spelling.format(literal=CLOCK_OFFSET_ENV_VAR, constant=alias or constant)
    return "\n".join(
        (
            "import os",
            f"{imported} as {alias}" if alias else imported,
            "def read() -> object:",
            f"    return {read}",
            "",
        )
    )
