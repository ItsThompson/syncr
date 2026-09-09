"""The construction sites a feed's values reach, declared in the tree and read by a test.

This table is the sweep, and it lives in the tree so that the tests can read it. A list of known
failures cannot fail when a new site is added; a table compared against the source can.

**What the class is.** A feed states values, and every value eventually reaches a constructor:
``int``, ``timedelta``, ``datetime``. Each of those refuses some inputs, and each refuses them by
raising something that is NOT an :class:`~syncr_api.calendars.ics_errors.IcsRejection`. For most of
them such an exception escapes ``IcsAdapter.fetch``, which is documented never to raise, and the
cost is a tenant's whole sync pass aborted with the sync state written in the same transaction
rolled back.

``Interval`` is the one member for which that is not the cost, and the difference belongs here
because every row of this table names a mechanism. ``IntervalError`` is listed in
:data:`~syncr_api.calendars.ics_errors.UNREPRESENTABLE`, so ``parse_feed`` nets it and answers with
a ``malformed-value`` rejection. An unguarded interval site therefore costs a **false rejection**
rather than an aborted pass: an event syncr could have placed becomes a panel entry blaming the
publisher. Smaller than the abort, still wrong, and still a harm a call-graph edit can introduce.

**How the table is used.** Two ways, and both matter:

- :func:`construction_calls` walks the package's own source for calls to a DECLARED constructor and
  :mod:`tests.test_ics_construction_sweep` asserts every one appears below with a stated guard. So a
  new unguarded read of that kind fails a test that names it, rather than waiting for a body that
  happens to reach it.
- :data:`MAGNITUDE_AXES` is derived from the same understanding and crossed into bodies by
  :mod:`tests.hostile_ics`, so the corpus enumerates the axes rather than listing the failures
  somebody found.

**What the table covers.** Calls to a declared constructor, and nothing else. The five exclusions
below are the whole of what it does not see; the generated corpus in :mod:`tests.hostile_ics` is the
other half, and it reaches an unguarded read whether or not the walk can see the call.

**The shapes the walk expresses.** It reads every ``.py`` file under the package, including
subpackages, identifies a module by its path relative to the package, and attributes each call to
its nearest enclosing ``def`` or ``class``. Two call shapes count, and :data:`EXPRESSED` carries a
source line for each so a test drives them rather than a reader trusting this paragraph:

- a bare name in :data:`CONSTRUCTORS`, so ``int(text)`` counts and ``Fraction(text)`` does not;
- an attribute whose receiver is a type in :data:`CONSTRUCTING_RECEIVERS`, whatever the attribute is
  called, so a sibling of ``strptime`` nobody has used yet is caught without being listed.

**A shape it cannot express, it refuses by name.** Both shapes match names in SOURCE, so a
constructor reached under a second name is a call the walk reports nothing for, and nothing is also
what it reports for a module that constructs nothing. Those two answers have to be distinguishable,
so :func:`construction_calls` raises :class:`InexpressibleShape`, naming the module, the line and
the binding, when a module aliases a declared constructor, assigns one to a second name, or hands
one to ``functools.partial``. :data:`REFUSED` carries a source line per binding.

That refusal is what makes a row's ``module`` key readable. A row says a call is in a module; an
alias in that module would have the census answer "no calls here" for a module full of them, and a
row that vanished for that reason looks exactly like a row whose call was deleted.

Five things it cannot see, stated because a reader who assumes otherwise is the reason this file
exists:

- **A binding the refusal does not model.** A constructor held in a container and reached through a
  subscript, ``_CONVERTERS["int"](text)``, is bound to no name either half reads.
  :data:`UNSEEN` carries it, so the claim is measured rather than asserted.
- **A second unguarded call inside a function that already has a row.** The comparison is over a set
  of ``(module, function, constructor)`` triples, so two ``int()`` calls in one function collapse to
  one row. A row says a function's conversions were considered, not that every one of them is
  guarded.
- **A callable outside :data:`CONSTRUCTORS`.** The bare-name half is an allowlist, so a construction
  through anything not listed is invisible: ``Fraction(text)`` and ``UUID(text)`` are not seen, and
  ``Decimal`` and ``Interval`` were both added by hand. One live example sits in the package still,
  ``rrulestr(...)``, guarded and not listed. The attribute half is not an allowlist, so any
  attribute on a datetime type is caught; generalising the bare-name half the same way needs a model
  of which callables can refuse, which this table does not have.
- **Arithmetic.** Overflow from ``instant - lead`` is not a call and cannot be found by walking for
  one; that is what the ``UNREPRESENTABLE`` net exists for.
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
#
# `Interval` is here for a related reason with a different cost. It refuses a non-positive or naive
# span with an `IntervalError`, which `UNREPRESENTABLE` lists, so `parse_feed` nets it: the pass
# survives and the component comes back as a `malformed-value` rejection. What the row protects is
# therefore not the pass but the ANSWER, because the bound that keeps the span positive lives in
# another module, at the read site, and a net is a fallback rather than a bound. Move the call away
# from that bound and a placeable event turns into a panel entry blaming the publisher.
# It is a bare name in this package, so the allowlist reaches it.
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
        "Interval",
    }
)


class InexpressibleShape(Exception):
    """A declared constructor is reachable here under a name neither call shape can read."""


# How a site is answered. Every row of the table below carries one of these, so "safe" is never a
# bare word: it names the mechanism a reader can go and check.
#
# There is deliberately no term for "an enclosing except in occurrences() answers it by name", which
# is a weaker guarantee: the conversion still raises and something further out catches it. Every row
# that would need it is guarded where it reads instead, so the term names nothing and is absent
# rather than left as vocabulary for a mechanism the package does not rely on.
#
# TOTAL_FOR_ACCEPTED_VALUES and BOUNDED_WHERE_IT_WAS_READ are the two that read alike and are not.
# The first is a predicate in the same function, checked before the call, so the site is answered by
# code a reader sees at once. The second is a refusal somewhere else entirely, which holds only as
# long as the call graph does, and a call graph is what a module split edits.
GUARDED_HERE: Final = "guarded at the read site"
GUARDED_BY_CALLER: Final = "guarded by an enclosing except in this package"
BOUNDED_BY_THE_PATTERN: Final = "bounded by the regex's fixed-width groups"
TOTAL_FOR_ACCEPTED_VALUES: Final = "total for the values its own predicate accepts, checked first"
BOUNDED_WHERE_IT_WAS_READ: Final = "bounded where the component was read, not here"
NOT_A_FEED_VALUE: Final = "constructed from syncr's own values, not the feed's"

# The vocabulary, closed. A row's guard has to be one of the terms above, or "stated guard" means
# only "some prose": the mechanism stops being one a reader can go and check. Each term appears here
# by reference, so a new one is declared once and this set cannot drift from the constants.
GUARDS: Final = frozenset(
    {
        GUARDED_HERE,
        GUARDED_BY_CALLER,
        BOUNDED_BY_THE_PATTERN,
        TOTAL_FOR_ACCEPTED_VALUES,
        BOUNDED_WHERE_IT_WAS_READ,
        NOT_A_FEED_VALUE,
    }
)


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
        function="_require_value_in_range",
        constructor="int",
        reads="a numeric rule member, to compare against the range its property allows",
        guard=GUARDED_HERE,
    ),
    Site(
        module="ics_recurrence",
        function="_signed",
        constructor="int",
        reads="a rule value, to decide whether it is a number at all",
        guard=GUARDED_HERE,
    ),
    Site(
        module="ics_recurrence",
        function="_number",
        constructor="int",
        reads="an INTERVAL a feed stated",
        guard=TOTAL_FOR_ACCEPTED_VALUES,
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
    # The one interval the placement half builds. Its bounds are the horizon and the event's own
    # length, and the length is a feed's magnitude, so the row belongs here rather than with the
    # constants: what keeps it from inverting is a refusal in another module.
    Site(
        module="ics_placement",
        function="_window",
        constructor="Interval",
        reads="the horizon widened backwards by the whole days or the span a feed stated",
        guard=BOUNDED_WHERE_IT_WAS_READ,
    ),
    Site(
        module="ics_times",
        function="module scope",
        constructor="timedelta",
        reads="nothing: it is the one-day constant",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="ics_times",
        function="resolve_span",
        constructor="Interval",
        reads="an occurrence's instant and the absolute span a feed stated",
        guard=BOUNDED_WHERE_IT_WAS_READ,
    ),
    Site(
        module="config",
        function="module scope",
        constructor="timedelta",
        reads="nothing: it is the poll interval",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="horizons",
        function="read_ingest_horizon",
        constructor="timedelta",
        reads="the write target's stored horizon, bounded by the schema",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="horizons",
        function="read_ingest_horizon",
        constructor="Interval",
        reads="nothing: it is now and the stored horizon, so its end follows its start",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="service",
        function="_bump_covered_weeks",
        constructor="timedelta",
        reads="a horizon the request schema already bounded",
        guard=NOT_A_FEED_VALUE,
    ),
    # The Google read path. A provider's values reach the same class of constructor a feed's do, so
    # they are declared in the same table: what changes is which parser gates them.
    Site(
        module="day_spans",
        function="module scope",
        constructor="timedelta",
        reads="nothing: it is the one-day constant",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="day_spans",
        function="module scope",
        constructor="time",
        reads="nothing: it is local midnight",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="day_spans",
        function="local_day_span",
        constructor="Interval",
        reads="local midnight on the first date and on the day after the last",
        guard=BOUNDED_WHERE_IT_WAS_READ,
    ),
    Site(
        module="feed_notices",
        function="markable_span",
        constructor="Interval",
        reads="local midnight today and the end of the ingest horizon",
        guard=GUARDED_HERE,
    ),
    Site(
        module="google_values",
        function="read_instant",
        constructor="fromisoformat",
        reads="an RFC 3339 date-time Google stated",
        guard=GUARDED_HERE,
    ),
    Site(
        module="google_values",
        function="read_date",
        constructor="fromisoformat",
        reads="an RFC 3339 full-date Google stated",
        guard=GUARDED_HERE,
    ),
    Site(
        module="google_values",
        function="_bounded",
        constructor="Interval",
        reads="the two instants Google stated, which it permits to be equal",
        guard=GUARDED_HERE,
    ),
    Site(
        module="google_backoff",
        function="stated_retry_after",
        constructor="float",
        reads="the Retry-After header Google sent",
        guard=GUARDED_HERE,
    ),
    Site(
        module="google_backoff",
        function="wait_before",
        constructor="float",
        reads="nothing: it is the doubling this schedule computed",
        guard=NOT_A_FEED_VALUE,
    ),
    Site(
        module="google_backoff",
        function="_jitter",
        constructor="float",
        reads="nothing: it is syncr's own random draw",
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
        _refuse_a_second_name(tree, module)
        for function, call in _calls_in(tree):
            name = _called_name(call)
            if name is not None:
                found.add((module, function, name))
    return found


# The wrappers that take a callable and return one, so a constructor handed to either is reached
# through the wrapper's name and never through its own.
_WRAPPERS: Final = frozenset({"partial", "partialmethod"})


def _refuse_a_second_name(tree: ast.Module, module: str) -> None:
    """Raise when this module can reach a declared constructor under a name the walk cannot read.

    Both shapes the walk expresses match names in source. A constructor bound to a second name is
    therefore a call it reports nothing for, and nothing is also what it reports for a module that
    constructs nothing, so the two have to be told apart somewhere. Here is that somewhere.

    There is no exemption, deliberately, and the blast radius is wide: one legitimate alias anywhere
    under the package raises out of :func:`construction_calls` and fails every test that calls it.
    ``date``, ``time`` and ``combine`` are ordinary names, so that is a real constraint on this
    package rather than a theoretical one. It is the right trade while an exemption list would be a
    second memory to keep, but a reader who trips it should know it is a rule and not a bug.
    """
    reachable = CONSTRUCTORS | CONSTRUCTING_RECEIVERS
    for node in ast.walk(tree):
        binding = _second_name(node, reachable)
        if binding is None:
            continue
        line, described = binding
        message = (
            f"{module}:{line} reaches a declared constructor as {described}, which the walk reads "
            "as no call at all. Call it by its own name, or the census reports this module empty."
        )
        raise InexpressibleShape(message)


def _second_name(node: ast.AST, reachable: frozenset[str]) -> tuple[int, str] | None:
    """The line and the description of the binding by which this node renames a constructor."""
    if isinstance(node, ast.Import | ast.ImportFrom):
        for alias in node.names:
            imported = alias.name.rsplit(".", 1)[-1]
            if alias.asname is not None and imported in reachable:
                return node.lineno, f"`{imported}` imported under `{alias.asname}`"
        return None
    if isinstance(node, ast.Assign | ast.AnnAssign):
        if isinstance(node.value, ast.Name) and node.value.id in reachable:
            return node.lineno, f"`{node.value.id}` assigned to a second name"
        return None
    if isinstance(node, ast.Call):
        wrapped = _wrapped_constructor(node, reachable)
        if wrapped is not None:
            return node.lineno, wrapped
    return None


def _wrapped_constructor(call: ast.Call, reachable: frozenset[str]) -> str | None:
    """The description of the constructor this call hands to a wrapper, if it hands one over."""
    func = call.func
    if isinstance(func, ast.Attribute):
        wrapper = func.attr
    elif isinstance(func, ast.Name):
        wrapper = func.id
    else:
        return None
    if wrapper not in _WRAPPERS or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Name) and first.id in reachable:
        return f"`{first.id}` wrapped by `{wrapper}`"
    return None


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
# The shapes this walk can and cannot express
# --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Shape:
    """A module source exhibiting one call or binding shape, and what the census owes it.

    ``triple`` is what the walk must report, for a shape it expresses. ``names`` is what the refusal
    must say, for a binding it refuses. A shape it neither expresses nor refuses sets neither, and
    that combination is the blind spot this module claims rather than a row nobody finished.

    Every source below is written against the module name ``probe``, so a triple names that module
    and a refusal quotes it.
    """

    what: str
    source: str
    triple: tuple[str, str, str] | None = None
    names: str = ""


# The two shapes a row can be about. Published as source rather than as prose, because a paragraph
# describing what an instrument sees is the instrument's own claim about itself.
EXPRESSED: Final = (
    Shape(
        what="a bare name in CONSTRUCTORS",
        source="def read(text):\n    return int(text)\n",
        triple=("probe", "read", "int"),
    ),
    Shape(
        what="an attribute on a constructing receiver, whatever the attribute is called",
        source="def read(text):\n    return datetime.fromtimestamp(text)\n",
        triple=("probe", "read", "fromtimestamp"),
    ),
)

# The bindings that reach a constructor under a second name. Each must raise rather than report an
# empty set, because an empty set is what a module with no constructions reports too.
REFUSED: Final = (
    Shape(
        what="an aliased import",
        source="from datetime import datetime as dt\n\n\ndef read(text):\n    return dt(text)\n",
        names="`datetime` imported under `dt`",
    ),
    Shape(
        what="an assignment to a second name",
        source="_convert = int\n\n\ndef read(text):\n    return _convert(text)\n",
        names="`int` assigned to a second name",
    ),
    Shape(
        what="a partial application",
        source="from functools import partial\n\n_convert = partial(int, base=16)\n",
        names="`int` wrapped by `partial`",
    ),
    Shape(
        what="a partial method",
        source="from functools import partialmethod\n\n_convert = partialmethod(int)\n",
        names="`int` wrapped by `partialmethod`",
    ),
)

# The blind spot, exhibited. A claimed limit is a claim, so this one is measured: the walk reports
# nothing here AND refuses nothing, which is the pair of answers a reader has to know it can give.
UNSEEN: Final = (
    Shape(
        what="a constructor in a container, reached through a subscript",
        source=(
            "_CONVERTERS = {'int': int}\n\n\ndef read(text):\n    return _CONVERTERS['int'](text)\n"
        ),
    ),
)


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
