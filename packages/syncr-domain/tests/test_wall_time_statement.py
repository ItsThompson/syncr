"""One statement of "this is a wall time", held against every shipped module.

`syncr_domain.snap.not_a_wall_time` is where this product says what a time of day may not
carry: a zone, or anything below a minute. Three modules stated that rule themselves before it
was stated once, each in its own words, and two of them disagreed about which half a value
carrying both breaks. So this file crosses the statement against the tree twice, because either
reading alone has a hole the other closes.

The SOURCE reading walks every shipped module and answers two questions of each: does it call
the statement, and does it decide anything from a time value's own ``tzinfo``, ``utcoffset``,
``second`` or ``microsecond``? A module that does the second is stating the rule itself, whatever
words it uses, so this catches a restatement that no search for a message would find. What it
cannot see is whether the name a module calls is really the statement's: a module that defined
its own ``not_a_wall_time`` would read as a reader.

The BEHAVIOUR reading closes that: the statement is substituted inside each reader's own module
for one that refuses a value the real one accepts, and each shape is then built through its
public constructor. A shape that restated the rule would keep accepting the value. A shape whose
refusal is unreachable through its constructor would too, which a test calling the raiser
directly could not tell.

WHAT NEITHER READING SEES, stated so a green result is not read as more than it is:

* the rule written over a value the reading cannot follow to a time: a module that computes
  ``divmod`` on a stored count of seconds, or reads a string's characters, states the same rule
  in arithmetic and names none of these attributes.
* an attribute reached through ``getattr`` or a name held in a value.
* which FIELD a reader names its refusal for. The source crossing is at module granularity, and
  the field identity is asserted per shape below instead.
* prose. A docstring may state the rule in words and disagree with the statement; only
  `syncr_domain.snap`'s own record is held to its text, by its own guard.
* every root outside the four this walk shares with the grid record's crossing, which are the
  ones a declaration can be refused from.

The walk itself, the module naming and the alias resolution are the grid record's, imported
rather than repeated: "which modules call this function" is the same question there.
"""

from __future__ import annotations

import ast
from datetime import UTC, time
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from syncr_domain import routines, snap, templates
from syncr_domain.routines import RoutineError, RoutineSpan, SpanField
from syncr_domain.snap import NotAWallTime, not_a_wall_time
from syncr_domain.templates import EntryField, EntrySpan, TemplateEntryError
from tests.test_package_boundary import scan
from tests.test_snap_record import module_of, package_of, repository_root, shipped_modules

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

# Derived from the imported objects rather than spelled out, so this crossing cannot be aimed at
# a function that is not the one the shapes below are built against.
STATEMENT: Final = f"{snap.__name__}.{not_a_wall_time.__name__}"
STATEMENT_MODULE: Final = snap.__name__

# What a value must not carry to be a wall time, as the attributes that answer it. `utcoffset` is
# here because it is the other way to ask about a zone; `fold` is not, because it names which of
# two real offsets applies rather than whether there is one.
DECIDING_ATTRIBUTES: Final = ("tzinfo", "utcoffset", "second", "microsecond")

# The shapes that read the statement, each of which owes the rule on its own field. A reader
# added later belongs here or not; nothing below requires the list to be the whole of them, so a
# new shape reading the statement reddens nothing.
READERS: Final = ("syncr_domain.routines", "syncr_domain.templates", "syncr_api.routines.schemas")

# Every shipped module that decides from a time value's own attributes rather than reading the
# statement, with what each one holds. Two different rules live in this list and the rows say
# which: a WALL TIME may carry no zone, and an INSTANT must carry one.
#
# A module that starts deciding this and is not here is a second statement of a rule that has
# one, and a module that stops is a row to delete.
DECIDES_WITHOUT_THE_STATEMENT: Final = {
    "syncr_domain.snap": (
        "the statement itself, beside the grid's two readings, which require a zero second "
        "because no quarter hour carries one"
    ),
    "syncr_domain.zones": (
        "refuses the zone half where it resolves a wall time against a date, because the "
        "combine would keep the offset and answer a different instant. The other half is not "
        "its business: it resolves a value rather than accepting a declaration"
    ),
    "syncr_domain.preferences": (
        "states both halves itself for a preferred window's bounds, which is the same rule in "
        "its own words on a shape this statement does not reach"
    ),
    "syncr_api.preferences.schemas": "the same, at the boundary that answers 422 for a window",
    "syncr_api.calendars.ics_values": (
        "refuses a zone on a feed's own wall value, which is a date and a time together rather "
        "than a time of day, and answers a malformed feed rather than a refused field"
    ),
    "syncr_domain.intervals": (
        "the instant rule: an interval bound names an instant, so it must carry a zone"
    ),
    "syncr_api.anchors.queries": "the instant rule, over a query's bounds",
    "syncr_learning.storage.documents": "the instant rule, reading a stored value back",
    "syncr_cli.arguments": "the instant rule, over what a caller typed",
    "syncr_cli.wire.reading": "the instant rule, over what the api answered",
}

# One value per shape the statement names, so nothing below counts on a list of them staying
# equal to the enum. A member with no value here fails the completeness test rather than going
# unasserted.
BREAKS_THE_RULE: Final = {
    NotAWallTime.CARRIES_A_ZONE: time(5, 0, tzinfo=UTC),
    NotAWallTime.BELOW_MINUTE_RESOLUTION: time(5, 0, 30),
}

# A value the real statement accepts, which is what makes a substituted statement visible: every
# shape below accepts it today, so a refusal can only come from the substitution.
ACCEPTED_BY_EVERY_SHAPE: Final = time(5, 0)


def holders_in(tree: ast.Module) -> Mapping[ast.AST, ast.AST]:
    """Each node mapped to the node that holds it, which is how a read's context is read."""
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def decides_something(node: ast.AST, holders: Mapping[ast.AST, ast.AST]) -> bool:
    """Whether this read reaches a question rather than a computation.

    ``at.second`` inside arithmetic is not a statement of the rule and ``replace(second=0)`` is
    not even a read. What counts is a read that reaches a comparison, a boolean operator, or the
    test of a branch, before it reaches the statement it sits in.
    """
    walker: ast.AST = node
    while True:
        holder = holders.get(walker)
        if holder is None:
            return False
        if isinstance(holder, ast.Compare | ast.BoolOp | ast.UnaryOp):
            return True
        if (
            isinstance(holder, ast.If | ast.IfExp | ast.While | ast.Assert)
            and holder.test is walker
        ):
            return True
        if isinstance(holder, ast.comprehension) and walker in holder.ifs:
            return True
        if isinstance(holder, ast.stmt):
            return False
        walker = holder


def rule_stated_in(source: str) -> tuple[str, ...]:
    """Which attributes of a time value this source decides something from."""
    tree = ast.parse(source)
    holders = holders_in(tree)
    return tuple(
        sorted(
            {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr in DECIDING_ATTRIBUTES
                and decides_something(node, holders)
            }
        )
    )


def reads_the_statement(path: Path, *, package: str) -> bool:
    """Whether this module calls the statement, however the call is spelled.

    Two arms, for the same reason the grid record's crossing has two: a dotted call resolves
    through the module's own aliases, and a bare call this module could only have reached through
    the statement's module is matched on the name alone, gated on importing that module.
    """
    scanned = scan(path, package)
    if STATEMENT in scanned.calls:
        return True
    return not_a_wall_time.__name__ in scanned.attributes and STATEMENT_MODULE in scanned.imports


def modules_deciding_without_the_statement() -> Mapping[str, tuple[str, ...]]:
    """Every shipped module that decides from a time value's attributes, with what it reads."""
    found: dict[str, tuple[str, ...]] = {}
    for relative, path in shipped_modules(repository_root()).items():
        stated = rule_stated_in(path.read_text(encoding="utf-8"))
        if stated:
            found[module_of(relative)] = stated
    return found


def modules_reading_the_statement() -> tuple[str, ...]:
    """Every shipped module that calls the statement."""
    return tuple(
        sorted(
            module_of(relative)
            for relative, path in shipped_modules(repository_root()).items()
            if reads_the_statement(path, package=package_of(relative))
        )
    )


# --------------------------------------------------------------------------------
# The controls on the source reading: which shapes state the rule, and which name one of
# these attributes without stating anything
# --------------------------------------------------------------------------------

STATEMENTS = [
    ("a zone refused against None", "if at.tzinfo is not None:\n    raise ValueError(at)\n"),
    ("the same, negated", "if not (at.tzinfo is None):\n    raise ValueError(at)\n"),
    ("a zone refused as a truth", "if at.tzinfo:\n    raise ValueError(at)\n"),
    (
        "a zone asked through its offset",
        "if at.utcoffset() is not None:\n    raise ValueError(at)\n",
    ),
    (
        "both sub-minute fields at once",
        "if at.second or at.microsecond:\n    raise ValueError(at)\n",
    ),
    ("a second against zero", "if at.second != 0:\n    raise ValueError(at)\n"),
    ("a microsecond above zero", "if at.microsecond > 0:\n    raise ValueError(at)\n"),
    ("the answer returned rather than raised", "def is_wall(at):\n    return at.tzinfo is None\n"),
    ("the answer as a conditional expression", "wall = at if at.tzinfo is None else None\n"),
    ("the read inside a comprehension's condition", "bad = [at for at in offered if at.second]\n"),
    ("the read asserted", "def check(at):\n    assert at.tzinfo is None\n"),
]


@pytest.mark.parametrize(("shape", "source"), STATEMENTS, ids=[shape for shape, _ in STATEMENTS])
def test_the_reading_finds_the_rule_stated_as(shape: str, source: str) -> None:
    assert rule_stated_in(source), f"the reading missed the rule stated as {shape}"


QUIET = [
    ("a sub-minute field zeroed rather than read", "floor = at.replace(second=0, microsecond=0)\n"),
    ("a field used in arithmetic", "total = at.second + at.microsecond / 1000000\n"),
    ("a field rendered", "shown = f'{at.second:02d}'\n"),
    ("the attribute named in prose", '"""A wall time carries no tzinfo and no second."""\n'),
    ("a zone attached rather than tested", "aware = at.replace(tzinfo=UTC)\n"),
    (
        "the statement read instead",
        "if not_a_wall_time(at) is not None:\n    raise ValueError(at)\n",
    ),
]


@pytest.mark.parametrize(("shape", "source"), QUIET, ids=[shape for shape, _ in QUIET])
def test_the_reading_finds_no_rule_in(shape: str, source: str) -> None:
    assert rule_stated_in(source) == (), f"the reading read {shape} as a statement of the rule"


CALLS = [
    (
        "an imported statement",
        "syncr_domain",
        "from syncr_domain.snap import not_a_wall_time\n"
        "def check(at):\n    return not_a_wall_time(at)\n",
    ),
    (
        "an aliased statement",
        "syncr_domain",
        "from syncr_domain.snap import not_a_wall_time as asked\n"
        "def check(at):\n    return asked(at)\n",
    ),
    (
        "the module imported from its package",
        "syncr_domain",
        "from syncr_domain import snap\ndef check(at):\n    return snap.not_a_wall_time(at)\n",
    ),
    (
        "the module imported by its full name",
        "syncr_domain",
        "import syncr_domain.snap\n"
        "def check(at):\n    return syncr_domain.snap.not_a_wall_time(at)\n",
    ),
    (
        "a statement imported relatively",
        "syncr_domain",
        "from .snap import not_a_wall_time\ndef check(at):\n    return not_a_wall_time(at)\n",
    ),
    (
        "the module imported relatively",
        "syncr_domain",
        "from . import snap\ndef check(at):\n    return snap.not_a_wall_time(at)\n",
    ),
]


@pytest.mark.parametrize(
    ("shape", "package", "source"), CALLS, ids=[shape for shape, _, _ in CALLS]
)
def test_the_crossing_finds_a_call_of_the_statement_spelled_as(
    shape: str, package: str, source: str, tmp_path: Path
) -> None:
    written = tmp_path / "reads.py"
    written.write_text(source, encoding="utf-8")

    assert reads_the_statement(written, package=package), f"the crossing missed {shape}"


NOT_CALLS = [
    ("an import with no call", "from syncr_domain.snap import not_a_wall_time\nASKED = None\n"),
    (
        "a function of the same name from somewhere else",
        "from syncr_api.wall import not_a_wall_time\n"
        "def check(at):\n    return not_a_wall_time(at)\n",
    ),
    (
        "the grid predicate, which answers the other question",
        "from syncr_domain.snap import is_wall_time_on_snap_grid\n"
        "def check(at):\n    return is_wall_time_on_snap_grid(at)\n",
    ),
]


@pytest.mark.parametrize(("shape", "source"), NOT_CALLS, ids=[shape for shape, _ in NOT_CALLS])
def test_the_crossing_reports_no_reading_for(shape: str, source: str, tmp_path: Path) -> None:
    written = tmp_path / "quiet.py"
    written.write_text(source, encoding="utf-8")

    assert not reads_the_statement(written, package="syncr_domain"), (
        f"the crossing counted {shape} as a reading of the statement"
    )


def test_the_walk_reads_the_checkout_the_statement_was_imported_from() -> None:
    # The crossing resolves the tree from a path and the statement from an imported object, so
    # without this it could hold one checkout's callers against another checkout's statement.
    walked = shipped_modules(repository_root())
    statement_source = Path(snap.__file__).resolve().relative_to(repository_root())

    assert str(statement_source) in walked


# --------------------------------------------------------------------------------
# The crossing: the readers read it, and nothing else in the tree states it
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("reader", READERS)
def test_the_shape_that_owes_the_rule_reads_the_statement(reader: str) -> None:
    reading = modules_reading_the_statement()

    assert reader in reading, (
        f"{reader} no longer calls {STATEMENT}, so the rule it applies is either its own "
        f"statement of one that has a home, or gone. The tree reads it in {list(reading)}"
    )


@pytest.mark.parametrize("reader", READERS)
def test_a_shape_that_reads_the_statement_states_no_rule_of_its_own(reader: str) -> None:
    stated = modules_deciding_without_the_statement()

    assert reader not in stated, (
        f"{reader} reads {STATEMENT} and decides from {stated.get(reader)} as well, so the rule "
        f"is stated twice again and the two can disagree"
    )


def test_every_module_that_states_the_rule_itself_is_one_this_list_names() -> None:
    stated = modules_deciding_without_the_statement()

    assert set(stated) == set(DECIDES_WITHOUT_THE_STATEMENT), (
        f"the tree decides from a time value's own attributes in "
        f"{dict(sorted(stated.items()))}. A module that reads a value's zone or its sub-minute "
        f"fields to decide whether it may be what it is either reads {STATEMENT} or says here "
        f"which rule it holds instead"
    )


# --------------------------------------------------------------------------------
# The behaviour: every shape the statement names is refused by every reader, on its own
# field, and each reader asks the statement rather than answering for itself
# --------------------------------------------------------------------------------


def test_every_shape_the_statement_names_has_a_value_here() -> None:
    # What keeps the two tests below from silently covering less than the statement says: a
    # member added to the rule with no value is unasserted rather than red without this.
    assert set(BREAKS_THE_RULE) == set(NotAWallTime)


@pytest.mark.parametrize(
    "broken", list(NotAWallTime), ids=[member.value for member in NotAWallTime]
)
def test_a_routine_span_refuses_every_shape_the_statement_names(broken: NotAWallTime) -> None:
    offered = BREAKS_THE_RULE[broken]

    assert not_a_wall_time(offered) is broken

    with pytest.raises(RoutineError) as refused:
        RoutineSpan(offered, 30, 30, 0)

    assert refused.value.field is SpanField.TARGET_TIME


@pytest.mark.parametrize(
    "broken", list(NotAWallTime), ids=[member.value for member in NotAWallTime]
)
def test_an_entry_span_refuses_every_shape_the_statement_names(broken: NotAWallTime) -> None:
    # The entry reads one member and reaches the other through the grid, which refuses every
    # sub-minute value. This is what says that composition covers the whole rule.
    offered = BREAKS_THE_RULE[broken]

    assert not_a_wall_time(offered) is broken

    with pytest.raises(TemplateEntryError) as refused:
        EntrySpan(target_time=offered, duration_minutes=30, flex_band_minutes=0)

    assert refused.value.field == EntryField.TARGET_TIME


def a_statement_refusing_everything(at: time) -> NotAWallTime | None:
    """A substitute that refuses what the real statement accepts, and nothing else changes."""
    assert at is not None
    return NotAWallTime.CARRIES_A_ZONE


SHAPES: list[tuple[str, object, Callable[[time], object]]] = [
    ("a routine's target time", routines, lambda at: RoutineSpan(at, 30, 30, 0)),
    (
        "a template entry's target time",
        templates,
        lambda at: EntrySpan(target_time=at, duration_minutes=30, flex_band_minutes=0),
    ),
]


@pytest.mark.parametrize(
    ("shape", "reader", "build"), SHAPES, ids=[shape for shape, _, _ in SHAPES]
)
def test_the_shape_asks_the_statement_at_the_moment_it_is_built(
    shape: str,
    reader: object,
    build: Callable[[time], object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The control first: the value is one every shape accepts, so the refusal below can only
    # come from the substitution.
    assert build(ACCEPTED_BY_EVERY_SHAPE) is not None

    monkeypatch.setattr(reader, not_a_wall_time.__name__, a_statement_refusing_everything)

    with pytest.raises((RoutineError, TemplateEntryError)):
        build(ACCEPTED_BY_EVERY_SHAPE)
