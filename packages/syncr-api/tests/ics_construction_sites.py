"""The construction sites a feed's values reach, declared in the tree and read by a test.

This table is the sweep. It exists in the repository, rather than in a review document, for one
reason: three rounds of this ticket were spent on the same class of defect, and each round fixed
the instances that had been found rather than the axis they sat on. A hand-written list of failures
cannot fail when a twelfth site is added. A table the tests read can.

**What the class is.** A feed states values, and every value eventually reaches a constructor:
``int``, ``timedelta``, ``datetime``. Each of those refuses some inputs, and each refuses them by
raising something that is NOT an :class:`~syncr_api.calendars.ics_errors.IcsRejection`. Such an
exception escapes ``IcsAdapter.fetch``, which is documented never to raise, and the cost was
measured three times: a tenant's whole sync pass aborted, and the sync state already written in the
same transaction rolled back with it.

**How the table is used.** Two ways, and both matter:

- :func:`construction_calls` walks the package's own source for constructor calls and
  :mod:`tests.test_ics_construction_sweep` asserts every one appears below with a stated guard. So a
  new unguarded read fails a test that names it, rather than waiting for a body that happens to
  reach it.
- :data:`MAGNITUDE_AXES` is derived from the same understanding and crossed into bodies by
  :mod:`tests.hostile_ics`, so the corpus enumerates the axes rather than listing the failures
  somebody found.

**Arithmetic is deliberately not in the call table.** Overflow from ``instant - lead`` is not a call
and cannot be found by walking for one; that is exactly what the ``UNREPRESENTABLE`` net exists for,
and the generated corpus is what exercises it. The table says so per row rather than pretending the
static walk covers it.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# The constructors that refuse an input by raising something no caller here declares. `int` is the
# one that started this: since CPython 3.11 it refuses a string over
# `sys.get_int_max_str_digits()` digits with a ValueError, which no part of this package's own
# vocabulary covers.
CONSTRUCTORS: Final = frozenset(
    {
        "int",
        "float",
        "timedelta",
        "datetime",
        "date",
        "time",
        "combine",
        "strptime",
        "fromisoformat",
    }
)

# How a site is answered. Every row of the table below carries one of these, so "safe" is never a
# bare word: it names the mechanism a reader can go and check.
GUARDED_HERE: Final = "guarded at the read site"
GUARDED_BY_CALLER: Final = "guarded by an enclosing except in this package"
NOT_A_FEED_VALUE: Final = "constructed from syncr's own values, not the feed's"


@dataclass(frozen=True, slots=True)
class Site:
    """One construction call, and how the value a feed supplied to it is answered."""

    module: str
    function: str
    constructor: str
    reads: str
    guard: str


# Every construction call in the calendars package, with the guard that answers it.
#
# A row is not documentation: `test_every_construction_call_is_declared` compares this against what
# the source actually contains, in both directions, so a site added without a row fails and a row
# whose site has gone fails too.
SITES: Final[tuple[Site, ...]] = (
    Site(
        module="ics_values",
        function="_number",
        constructor="int",
        reads="one digit group of a DURATION",
        guard=GUARDED_HERE,
    ),
    Site(
        module="ics_values",
        function="parse_sequence",
        constructor="int",
        reads="a SEQUENCE value",
        guard=GUARDED_HERE,
    ),
    Site(
        module="ics_values",
        function="_parse_date",
        constructor="int",
        reads="the year, month and day of a DATE",
        guard=GUARDED_BY_CALLER,
    ),
    Site(
        module="ics_values",
        function="parse_time",
        constructor="int",
        reads="the six fields of a DATE-TIME",
        guard=GUARDED_BY_CALLER,
    ),
    Site(
        module="ics_values",
        function="_build",
        constructor="datetime",
        reads="the fields a DATE or DATE-TIME named",
        guard=GUARDED_HERE,
    ),
    Site(
        module="ics_values",
        function="parse_duration",
        constructor="timedelta",
        reads="the summed seconds of a DURATION",
        guard=GUARDED_HERE,
    ),
    Site(
        module="ics_recurrence",
        function="_as_series_wall",
        constructor="strptime",
        reads="a UTC UNTIL inside an RRULE",
        guard=GUARDED_BY_CALLER,
    ),
    Site(
        module="ics_times",
        function="module scope",
        constructor="timedelta",
        reads="nothing: it is the one-day constant",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="config",
        function="module scope",
        constructor="timedelta",
        reads="nothing: it is the poll interval",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="injection",
        function="read_ingest_horizon",
        constructor="timedelta",
        reads="the write target's stored horizon, bounded by the schema",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="service",
        function="_bump_covered_weeks",
        constructor="timedelta",
        reads="a horizon the request schema already bounded",
        guard=NOT_A_FEED_VALUE,
    ),
)


def construction_calls(source_root: Path, package: str) -> set[tuple[str, str, str]]:
    """Every ``(module, function, constructor)`` the package's source constructs with.

    Read from the source rather than from a registry, because the point is to notice a call nobody
    declared. A call at module scope is reported against ``"module scope"``, so a constant is
    accounted for rather than invisible.
    """
    found: set[tuple[str, str, str]] = set()
    for path in sorted((source_root / package).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function, call in _calls_in(tree):
            name = _called_name(call)
            if name in CONSTRUCTORS:
                found.add((path.stem, function, name))
    return found


def _calls_in(tree: ast.Module) -> Iterator[tuple[str, ast.Call]]:
    """Every call in a module, paired with the function that contains it."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                yield node.name, inner
    for node in tree.body:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and not _inside_a_function(node):
                yield "module scope", inner


def _inside_a_function(node: ast.stmt) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)


# The names a construction can be reached through as an attribute. `datetime.combine(...)` builds a
# value; `moment.date()` reads one off a value that already exists and cannot fail. Distinguishing
# them by the RECEIVER is what keeps the table about conversions rather than about accessors.
CONSTRUCTING_RECEIVERS: Final = frozenset({"datetime", "date", "time", "timedelta"})


def _called_name(call: ast.Call) -> str | None:
    """The bare name of what a call constructs, or ``None`` when it constructs nothing.

    A bare name is a constructor if it is one. An attribute is a constructor only when its
    receiver is
    one of the datetime types: ``datetime.strptime`` builds a value from a string a feed supplied,
    while ``wall.date()`` projects a value that already exists and has nothing left to refuse.
    """
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        receiver = call.func.value
        if isinstance(receiver, ast.Name) and receiver.id in CONSTRUCTING_RECEIVERS:
            return call.func.attr
    return None


# --------------------------------------------------------------------------------
# The axes the generated corpus crosses
# --------------------------------------------------------------------------------

# One digit group past what `int()` will convert. Read from the interpreter rather than written as
# 4301, because the limit is settable and a literal would stop testing the boundary the moment a
# deployment changed it.
PAST_INT_CONVERSION: Final = "9" * (sys.get_int_max_str_digits() + 1)

# The last group `int()` still converts, so the corpus holds both sides of that boundary.
AT_INT_CONVERSION: Final = "9" * sys.get_int_max_str_digits()
