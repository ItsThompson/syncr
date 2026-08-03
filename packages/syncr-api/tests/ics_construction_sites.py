"""The construction sites a feed's values reach, declared in the tree and read by a test.

This table is the sweep, and it lives in the tree so that the tests can read it. A list of known
failures cannot fail when a new site is added; a table compared against the source can.

**What the class is.** A feed states values, and every value eventually reaches a constructor:
``int``, ``timedelta``, ``datetime``. Each of those refuses some inputs, and each refuses them by
raising something that is NOT an :class:`~syncr_api.calendars.ics_errors.IcsRejection`. Such an
exception escapes ``IcsAdapter.fetch``, which is documented never to raise, and the cost is a
tenant's whole sync pass aborted with the sync state written in the same transaction rolled back.

**How the table is used.** Two ways, and both matter:

- :func:`construction_calls` walks the package's own source for calls to a DECLARED constructor and
  :mod:`tests.test_ics_construction_sweep` asserts every one appears below with a stated guard. So a
  new unguarded read of that kind fails a test that names it, rather than waiting for a body that
  happens to reach it.
- :data:`MAGNITUDE_AXES` is derived from the same understanding and crossed into bodies by
  :mod:`tests.hostile_ics`, so the corpus enumerates the axes rather than listing the failures
  somebody found.

**Arithmetic is deliberately not in the call table.** Overflow from ``instant - lead`` is not a call
and cannot be found by walking for one; that is exactly what the ``UNREPRESENTABLE`` net exists for,
and the generated corpus is what exercises it.

**What the walk does and does not see.** It reads every ``.py`` file under the package, including
subpackages, identifies a module by its path relative to the package, and attributes each call to
its nearest enclosing ``def`` or ``class``. An attribute call counts whenever its receiver is a
type, so a sibling of ``strptime`` nobody has used yet is caught without being listed.

Three things it cannot see, stated because a reader who assumes otherwise is the reason this file
exists:

- **An aliased or indirect binding.** ``from datetime import datetime as dt`` then ``dt(...)``, or
  ``_convert = int``, or ``functools.partial(int, ...)``. The walk matches names in source, so a
  rebound constructor is invisible to it.
- **A second unguarded call inside a function that already has a row.** The comparison is over a set
  of ``(module, function, constructor)`` triples, so two ``int()`` calls in one function collapse to
  one row. A row says a function's conversions were considered, not that every one of them is
  guarded.
- **A callable outside :data:`CONSTRUCTORS`.** The bare-name half is an allowlist, so a construction
  through anything not listed is invisible: ``Fraction(text)`` and ``UUID(text)`` are not seen, and
  ``Decimal`` had to be added by hand. Two live examples sit in the package already,
  ``Interval(...)`` and ``rrulestr(...)``, both guarded and neither listed. The attribute half is
  not an allowlist, so any attribute on a datetime type is caught; generalising the bare-name half
  the same way needs a model of which callables can refuse, which this table does not have.
- **Arithmetic.** Overflow from ``instant - lead`` is not a call and cannot be found by walking for
  one; that is exactly what the ``UNREPRESENTABLE`` net exists for.
- **A library that validates late.** ``rrulestr`` accepts a negative ``INTERVAL`` and raises during
  iteration, nowhere near the call. A static walk cannot see that, and two escapes were found that
  way rather than by this table.

All of these are why the generated corpus is the other half rather than a supplement: a body that
reaches an unguarded read fails a test whether or not the walk can see the call.
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
        "Decimal",
        "timedelta",
        "datetime",
        "date",
        "time",
        "timezone",
        "combine",
        "strptime",
        "fromisoformat",
        "ZoneInfo",
    }
)

# How a site is answered. Every row of the table below carries one of these, so "safe" is never a
# bare word: it names the mechanism a reader can go and check.
GUARDED_HERE: Final = "guarded at the read site"
GUARDED_BY_CALLER: Final = "guarded by an enclosing except in this package"
BOUNDED_BY_THE_PATTERN: Final = "bounded by the regex's fixed-width groups"
BOUNDED_BY_THE_CALLER_S_CATCH: Final = "an enclosing except in occurrences() answers it by name"
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
        guard=BOUNDED_BY_THE_PATTERN,
    ),
    Site(
        module="ics_values",
        function="parse_time",
        constructor="int",
        reads="the six fields of a DATE-TIME",
        guard=BOUNDED_BY_THE_PATTERN,
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
        function="_require_positive_interval",
        constructor="int",
        reads="an INTERVAL a feed stated",
        guard=BOUNDED_BY_THE_CALLER_S_CATCH,
    ),
    Site(
        module="ics_recurrence",
        function="_require_selectable_setpos",
        constructor="int",
        reads="a BYSETPOS position a feed stated",
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
        module="ics_recurrence",
        function="_as_series_wall",
        constructor="ZoneInfo",
        reads="the literal 'UTC', and a zone resolve_tzid already accepted",
        guard=NOT_A_FEED_VALUE,
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

    ``module`` is the path RELATIVE to the package, without the suffix, so ``providers/config.py``
    is reported as ``providers/config``, not absorbed by the row for the ``config`` beside it.
    """
    root = source_root / package
    found: set[tuple[str, str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = path.relative_to(root).with_suffix("").as_posix()
        for function, call in _calls_in(tree):
            name = _called_name(call)
            if name is not None:
                found.add((module, function, name))
    return found


def _calls_in(tree: ast.Module) -> Iterator[tuple[str, ast.Call]]:
    """Every call in a module, paired with the innermost scope that contains it.

    Each call is attributed to its nearest enclosing ``def`` or ``class``, so a call in an ``if``
    inside a method is reported against the method, not the module. A class body is a scope of its
    own: a conversion evaluated there runs at import and can still refuse.
    """
    scopes: dict[ast.AST, str] = {}
    for parent in ast.walk(tree):
        inherited = scopes.get(parent, "module scope")
        for child in ast.iter_child_nodes(parent):
            scopes[child] = _scope_name(parent) or inherited
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield scopes.get(node, "module scope"), node


def _scope_name(node: ast.AST) -> str | None:
    """The name this node introduces as a scope, or ``None`` when it introduces none."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name
    return None


# The names a construction can be reached through as an attribute. `datetime.combine(...)` builds a
# value; `moment.date()` reads one off a value that already exists and cannot fail. Distinguishing
# them by the RECEIVER is what keeps the table about conversions rather than about accessors.
CONSTRUCTING_RECEIVERS: Final = frozenset({"datetime", "date", "time", "timedelta"})


def _called_name(call: ast.Call) -> str | None:
    """What this call constructs, or ``None`` when it constructs nothing.

    Two rules, and the second is deliberately not an allowlist. A bare name counts when it is in
    :data:`CONSTRUCTORS`. An attribute counts whenever its RECEIVER is a datetime type, whatever the
    attribute is called: ``datetime.strptime`` and ``datetime.fromtimestamp`` both build a value
    from something a feed supplied, and listing the ones that exist today would leave the next one
    invisible. ``wall.date()`` is not caught, because ``wall`` is a value rather than a type, and a
    projection off an existing value has nothing left to refuse.
    """
    if isinstance(call.func, ast.Name):
        return call.func.id if call.func.id in CONSTRUCTORS else None
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
#
# Clamped to the DEFAULT limit as a floor, because `sys.set_int_max_str_digits(0)` disables the
# limit entirely: read raw, the axis would degenerate to one digit and six corpus bodies would send
# a one-digit duration while their labels claimed a past-limit one. The axis follows the limit
# upward, and refuses to follow it into meaninglessness.
_CONVERSION_LIMIT: Final = max(sys.get_int_max_str_digits(), 4300)

PAST_INT_CONVERSION: Final = "9" * (_CONVERSION_LIMIT + 1)

# The last group `int()` still converts, so the corpus holds both sides of that boundary.
AT_INT_CONVERSION: Final = "9" * _CONVERSION_LIMIT

# A group past what `int()` will convert whose SIGNIFICANT digits are well inside every bound syncr
# owns. RFC 5545's `\d+` permits leading zeros, so this is a legitimate way to write one second, and
# it separates the two counts a reader can confuse: a bound on the significant digits does not
# protect the conversion unless the stripped value is what gets converted.
PADDED_PAST_INT_CONVERSION: Final = "0" * (_CONVERSION_LIMIT + 1) + "1"
