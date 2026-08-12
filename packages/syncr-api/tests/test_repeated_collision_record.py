"""The record beside the null-series rule, and the two ways of filling it in that it declines.

``reviews/collisions.py`` skips a conflict row carrying no series, and its docstring now records
that two alternatives were weighed and declined: filling the rows whose anchor still exists, and
grouping on the stored title instead. Prose rots, so every clause of that record is asserted here,
and every claim it makes about the tree is crossed against the tree:

* the clauses themselves, read off the SHIPPED module rather than off a copy, so the record cannot
  be satisfied by the same words in a neighbouring file or in another section of this one;
* the wait the record states, derived from the constant the session actually reads;
* what the declined title reading would do, implemented here and measured, in both directions;
* that nothing fills an old row in: not the migration chain, and not the application;
* and the mechanism the first reason rests on, which is that recurrence is expanded forward from
  now, so the anchors that survive are the recent ones.

Every scan returns data rather than asserting, so each reading is exercised against the real tree
AND against synthetic source. A reading that has quietly stopped finding anything otherwise passes
forever.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import pytest

import syncr_api
from syncr_api.calendars.config import (
    HORIZON_DAYS_DEFAULT,
    HORIZON_DAYS_MAX,
    ICS,
    WRITE_TARGET,
)
from syncr_api.calendars.horizons import read_ingest_horizon
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.plans.records import ConflictRecord
from syncr_api.reviews import collisions
from syncr_api.reviews.collisions import repeated_collisions
from syncr_api.reviews.config import REPEATED_COLLISION_WEEKS
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from syncr_api.calendars.repository import CalendarSourceRepository
    from syncr_domain.zones import Date

# The heading of the section the record has to sit in. The rule and the declines are one statement:
# a reader meets the skip and the reason it is not a gap in the same breath, or the record is filed
# somewhere they will not look.
RULE_HEADING: Final = "## A commitment with no series never contributes"

# The table and the column a backfill would have to write, and the chain that could write them.
CONFLICTS_TABLE: Final = "conflicts"
SERIES_COLUMN: Final = "series_uid"
REVISIONS: Final = "packages/syncr-api/alembic/versions"

# Below this the glob has stopped reading the chain and every set derived from it is empty by
# construction rather than by fact.
REVISIONS_FLOOR: Final = 20

# Every root holding code that could write the column outside the chain.
SHIPPED_ROOTS: Final = ("packages/*/src", "cli/src")
MODULES_FLOOR: Final = 300

# The three names a data statement reaches the database through. DDL goes through `op.add_column`
# and its siblings, so a reading keyed on these three sees row writes and nothing else.
STATEMENT_CALLS: Final = frozenset({"execute", "executemany", "bulk_insert"})

# A write statement spelled as SQL, and a write statement built over a named table. Both are needed:
# the chain holds one of each, and neither reading can see the other's shape.
WRITE_VERB: Final = re.compile(r"\b(?:update|insert\s+into|delete\s+from)\s+", re.IGNORECASE)
# `(?<!\w)` is what keeps this off `create_table`, which is DDL: the chain creates the conflicts
# table with a literal name, and a reading that counted that saw a write in every table it made.
NAMED_TABLE: Final = re.compile(r"(?<!\w)(?:sa\.)?table\(\s*[\"']([a-z_]+)[\"']", re.IGNORECASE)

WEEKS_IN_WORDS: Final = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


# --------------------------------------------------------------------------------
# Reading the record off the shipped module
# --------------------------------------------------------------------------------


def repository_root() -> Path:
    """The checkout the imported package came from, which is the tree every scan below reads."""
    return Path(syncr_api.__file__).resolve().parents[4]


def sections(docstring: str) -> Mapping[str, str]:
    """A module docstring split at its own headings, keyed by the heading line."""
    found: dict[str, list[str]] = {"": []}
    heading = ""
    for line in docstring.splitlines():
        if line.startswith("## "):
            heading = line
            found[heading] = []
            continue
        found[heading].append(line)
    return {name: "\n".join(body) for name, body in found.items()}


def record() -> str:
    """The section of the shipped module's own docstring that carries the rule and the declines.

    Read from the module object, so a record moved into a sibling file or into another section of
    this one is absent rather than found somewhere a reader would not meet the rule. A file holding
    no such heading answers with nothing, which is what every clause below is asserted against.
    """
    held = sections(collisions.__doc__ or "")
    named = [heading for heading in held if heading.startswith(RULE_HEADING)]
    return "\n".join(held[heading] for heading in named)


def collapsed(text: str) -> str:
    """One line, so a reflow of the record is safe and a rewording is not."""
    return " ".join(text.split())


def test_the_record_is_read_from_the_module_this_checkout_ships() -> None:
    # The control for every clause below: the record is read off the imported module and the tree
    # scans resolve a checkout, so a run against a copy could otherwise read one and scan the other.
    assert Path(collisions.__file__).resolve() == (
        repository_root() / "packages/syncr-api/src/syncr_api/reviews/collisions.py"
    )
    assert repository_root() == Path(__file__).resolve().parents[3]


def test_the_rule_and_its_declined_alternatives_are_one_section() -> None:
    # The placement claim, and the reason the clause list is read from a section rather than from
    # the file: the skip and the reasons it is not a gap are one statement, so a reader meets both
    # or neither. Every word of the record could be in this file and fail this.
    held = record()

    assert "A one-off cannot recur" in held
    assert "The first is a PARTIAL BACKFILL" in held
    assert "The second is READING" in held


@pytest.mark.parametrize(
    "clause",
    [
        pytest.param("weighed and both are declined", id="both-ways-were-weighed"),
        pytest.param(
            "a raise that stays quiet about an old plan is this rule working rather than a defect",
            id="the-quiet-raise-is-the-rule-working",
        ),
        pytest.param("The first is a PARTIAL BACKFILL", id="the-declined-partial-backfill"),
        pytest.param(
            "join a row carrying no series to the anchor it names and copy the series",
            id="what-the-backfill-would-do",
        ),
        pytest.param(
            "only reaches the rows whose anchor still exists", id="what-a-backfill-can-reach"
        ),
        pytest.param(
            "Those are the recent ones by construction",
            id="the-surviving-anchors-are-the-recent-ones",
        ),
        pytest.param("recurrence is expanded from now forward", id="why-they-are-the-recent-ones"),
        pytest.param(
            "reconciliation deletes it at the next successful read",
            id="what-destroys-an-old-anchor",
        ),
        pytest.param(
            "calendar weeks for a commitment that recurs weekly, and more for a sparser one",
            id="the-wait-is-conditional",
        ),
        pytest.param(
            "at most the weeks the projection horizon already covers",
            id="the-bound-on-what-the-backfill-buys",
        ),
        pytest.param(
            "What would reopen it is the expansion reading backwards",
            id="what-would-reopen-the-backfill",
        ),
        pytest.param("The second is READING ``commitment_title``", id="the-declined-title-reading"),
        pytest.param(
            "A title cannot tell a one-off from a series", id="why-the-title-reading-is-declined"
        ),
        pytest.param(
            "appointments a publisher happened to name the same thing become a repetition",
            id="the-title-reading-invents-a-repetition",
        ),
        pytest.param(
            "one series renamed mid-run becomes two shorter runs",
            id="the-title-reading-splits-a-real-one",
        ),
        pytest.param(
            "the title would state something the reader cannot check",
            id="what-the-title-reading-would-cost",
        ),
    ],
)
def test_the_record_still_states(clause: str) -> None:
    assert clause in collapsed(record())


def test_the_record_states_the_wait_the_session_actually_reads() -> None:
    # The one figure the record spells, crossed against the constant that decides it rather than
    # restated beside it: a threshold moved to four weeks makes this sentence false, loudly.
    assert REPEATED_COLLISION_WEEKS in WEEKS_IN_WORDS, "this crossing needs the word for the count"
    stated = f"once {WEEKS_IN_WORDS[REPEATED_COLLISION_WEEKS]} of its weeks have collided"

    assert stated in collapsed(record())


# --------------------------------------------------------------------------------
# The record cites no planning artifact
# --------------------------------------------------------------------------------

# Scoped to the record rather than to the file: the rest of the module's prose is not this record's
# to police.
BANNED_SHAPES: Final = (
    ("a-ticket-number", re.compile(r"\bticket\s+\d+", re.IGNORECASE)),
    ("a-story-id", re.compile(r"\bUS-[A-Z]+-\d+")),
    ("an-epic-ticket-id", re.compile(r"\b[A-Z]+\d+-[A-Z]+-\d+")),
    ("an-acceptance-criterion", re.compile(r"\bAC\s?\d+\b")),
    ("a-spec-section", re.compile(r"\bsections?\s+\d+|§\s?\d+")),
    ("a-spec-document", re.compile(r"\b\d\d-[a-z-]+\.md\b")),
    ("a-review-round", re.compile(r"\breview[- ]\d+\b|\bround\s+\d+\b", re.IGNORECASE)),
    ("delivery-plan-language", re.compile(r"\b(?:slice|milestone|wave)\b", re.IGNORECASE)),
)

# One line each, in the shape the ban is about, so a pattern that matches nothing cannot pass as a
# guard. Every sample is a sentence somebody could plausibly have written into the record.
SHAPE_SAMPLES: Final = {
    "a-ticket-number": "the partial backfill ticket 1511 asked for is declined",
    "a-story-id": "the raise US-REV-05 states is unaffected",
    "an-epic-ticket-id": "declined under SP1-PLAN-30",
    "an-acceptance-criterion": "AC3 is what this paragraph answers",
    "a-spec-section": "the reasoning is in section 11 of the specification",
    "a-spec-document": "derived in 06-decisions-register.md",
    "a-review-round": "raised by review-51 and closed in round 2",
    "delivery-plan-language": "a later slice may revisit the backfill",
}


@pytest.mark.parametrize(("named", "shape"), BANNED_SHAPES, ids=[one for one, _ in BANNED_SHAPES])
def test_every_banned_shape_matches_its_own_sample(named: str, shape: re.Pattern[str]) -> None:
    assert shape.search(SHAPE_SAMPLES[named]) is not None


@pytest.mark.parametrize(("named", "shape"), BANNED_SHAPES, ids=[one for one, _ in BANNED_SHAPES])
def test_the_record_names_no_planning_artifact(named: str, shape: re.Pattern[str]) -> None:
    assert shape.search(record()) is None, named


# --------------------------------------------------------------------------------
# What the declined title reading would do, measured
# --------------------------------------------------------------------------------

LEETCODE: Final = uuid4()
RUN: Final = (IsoWeek(2026, 6), IsoWeek(2026, 7), IsoWeek(2026, 8), IsoWeek(2026, 9))
NOW: Final = datetime(2026, 2, 9, 9, tzinfo=UTC)


def an_instant(on: Date, hour: int) -> datetime:
    return datetime.combine(on, time(hour), tzinfo=UTC)


def a_conflict(*, iso_week: IsoWeek, series_uid: str | None, title: str | None) -> ConflictRecord:
    """One retained conflict over one block, carrying whichever key the case is about."""
    monday = iso_week.monday()
    return ConflictRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        iso_week=iso_week,
        anchor_id=uuid4(),
        block_id=f"{iso_week}-{uuid4()}",
        binding=BindingRef.for_task(LEETCODE),
        series_uid=series_uid,
        commitment_title=title,
        overlap=Interval(an_instant(monday, 9), an_instant(monday, 10)),
        detected_at=an_instant(monday, 9),
        resolved_at=None,
        resolution=None,
    )


def grouped_on_the_title(
    conflicts: Sequence[ConflictRecord], *, at_least_weeks: int
) -> list[tuple[str, int]]:
    """The declined reading: group on ``commitment_title`` where the series is what a row lacks.

    Not shipped, and here to be measured rather than used. It is the same grouping the module does,
    with the title standing in for the series, which is the only other key such a row carries.
    """
    grouped: dict[tuple[str, object], set[IsoWeek]] = {}
    for conflict in conflicts:
        if conflict.commitment_title is None:
            continue
        key = (conflict.commitment_title, conflict.binding.content_key)
        grouped.setdefault(key, set()).add(conflict.iso_week)
    return sorted(
        (title, len(weeks)) for (title, _), weeks in grouped.items() if len(weeks) >= at_least_weeks
    )


class TestWhatTheTitleReadingWouldDo:
    def test_it_raises_a_repetition_out_of_unrelated_one_offs(self) -> None:
        # Separate appointments a publisher named the same thing. Each carries no series because
        # each IS a one-off, so the title is all the alternative has to group on, and it groups
        # them into a pattern the reader cannot check.
        dentist = [
            a_conflict(iso_week=week, series_uid=None, title="Dentist")
            for week in RUN[:REPEATED_COLLISION_WEEKS]
        ]

        assert grouped_on_the_title(dentist, at_least_weeks=REPEATED_COLLISION_WEEKS) == [
            ("Dentist", REPEATED_COLLISION_WEEKS)
        ]
        assert repeated_collisions(dentist, at_least_weeks=REPEATED_COLLISION_WEEKS) == []

    def test_it_loses_a_real_series_that_was_renamed(self) -> None:
        # The other direction. One series, retitled twice by its publisher, is one pattern: the
        # shipped reading groups it on the series and names it whatever the newest row called it.
        # The title reading splits it into runs of one, each too short to raise.
        renamed = [
            a_conflict(iso_week=week, series_uid="standup-series", title=title)
            for week, title in zip(RUN, ("Standup", "Stand-up", "Daily sync"), strict=False)
        ]

        assert grouped_on_the_title(renamed, at_least_weeks=REPEATED_COLLISION_WEEKS) == []

        (found,) = repeated_collisions(renamed, at_least_weeks=REPEATED_COLLISION_WEEKS)
        assert found.week_count == REPEATED_COLLISION_WEEKS
        assert found.commitment == "Daily sync"

    def test_the_two_readings_agree_where_neither_key_is_ambiguous(self) -> None:
        # The control that stops the two tests above reading as "the alternative never works": one
        # series under one stable title is raised by both, so what they disagree about is the key
        # rather than the arithmetic.
        stable = [
            a_conflict(iso_week=week, series_uid="standup-series", title="Standup")
            for week in RUN[:REPEATED_COLLISION_WEEKS]
        ]

        assert grouped_on_the_title(stable, at_least_weeks=REPEATED_COLLISION_WEEKS) == [
            ("Standup", REPEATED_COLLISION_WEEKS)
        ]
        assert (
            repeated_collisions(stable, at_least_weeks=REPEATED_COLLISION_WEEKS)[0].week_count
            == REPEATED_COLLISION_WEEKS
        )


# --------------------------------------------------------------------------------
# Nothing fills an old row in: the migration chain
# --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Statement:
    """One data statement a revision runs, and the text this reading could resolve for it."""

    revision: str
    call: str
    text: str


def revision_sources() -> Mapping[str, str]:
    """Every revision in the chain, by file name."""
    versions = repository_root() / REVISIONS
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(versions.glob("*.py"))}


def data_statements(source: str, *, revision: str) -> tuple[Statement, ...]:
    """Every row-writing statement this module runs, with the names it spells resolved.

    Reads the calls rather than the file, so a docstring describing a write is prose and a call is a
    finding. The chain's own convention is to spell a statement as a module constant and execute the
    name, and to interpolate the table and column names declared above it, so the resolution has to
    follow an f-string as well as a plain string: without that, the one backfill the chain already
    holds resolves to the bare name of its constant and no reading of it can name a table.
    """
    tree = ast.parse(source)
    spelled = _spelled_constants(tree)
    found: list[Statement] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in STATEMENT_CALLS:
            continue
        written = ast.unparse(node)
        for name, value in spelled.items():
            written = re.sub(rf"\b{re.escape(name)}\b", value.replace("\\", ""), written)
        found.append(Statement(revision=revision, call=ast.unparse(node), text=written))
    return tuple(found)


def _spelled_constants(tree: ast.Module) -> Mapping[str, str]:
    """Every module-level name this file binds to text, in the order the file binds them."""
    known: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        rendered = _rendered(node.value, known)
        if rendered is None:
            continue
        known.update(
            {target.id: rendered for target in node.targets if isinstance(target, ast.Name)}
        )
    return known


def _rendered(node: ast.expr, known: Mapping[str, str]) -> str | None:
    """This expression as the text it produces, or nothing when it produces no text.

    A part an f-string interpolates that this cannot resolve is kept as the name it was written as,
    rather than dropped: a dropped part turns ``UPDATE {TABLE} SET`` into a statement naming no
    table at all, which is the one answer a reading of writes must not produce.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.FormattedValue):
        return _rendered(node.value, known) or ast.unparse(node.value)
    if isinstance(node, ast.JoinedStr):
        parts = [_rendered(value, known) for value in node.values]
        return "".join(part for part in parts if part is not None)
    if isinstance(node, ast.Call) and node.args:
        return _rendered(node.args[0], known)
    return None


def writes_naming(source: str, *, table: str) -> tuple[str, ...]:
    """Every write statement in this text that names one table, read as text rather than as code.

    The second reading, and it covers what the first cannot classify: a statement built over a
    table constructed inline is a call whose unparsed text names a local, so only the literal table
    name in the source can be crossed against a table.
    """
    found = [
        source[spelled.start() : spelled.end() + len(table)].strip()
        for spelled in WRITE_VERB.finditer(source)
        if _first_word(source[spelled.end() :]) == table
    ]
    found.extend(
        match.group(0) for match in NAMED_TABLE.finditer(source) if match.group(1) == table
    )
    return tuple(found)


def _first_word(tail: str) -> str:
    """The identifier a statement names next, however it is quoted or terminated."""
    words = tail.split()
    return words[0].strip("\"'`;,()") if words else ""


A_SYNTHETIC_BACKFILL: Final = '''
"""A revision that fills the fillable end in."""

FILL_FROM_THE_SURVIVING_ANCHORS = (
    "UPDATE conflicts SET series_uid = anchors.series_uid, commitment_title = anchors.title "
    "FROM anchors WHERE anchors.id = conflicts.anchor_id AND conflicts.series_uid IS NULL"
)


def upgrade() -> None:
    op.execute(FILL_FROM_THE_SURVIVING_ANCHORS)
'''

A_SYNTHETIC_TABLE_BACKFILL: Final = """
def upgrade() -> None:
    rows = sa.table("conflicts", sa.column("series_uid", sa.String))
    op.execute(rows.update().values(series_uid="filled"))
"""


def fills_the_series_in(source: str, *, revision: str) -> tuple[str, ...]:
    """Everything either reading says fills a conflict row's series in, as it was written.

    Both readings, because a backfill has two shapes and each reading is blind to one of them: a
    statement whose table name is interpolated from a constant resolves to text the call reading
    can cross against a table and the text reading cannot, and a statement built over a table
    constructed inline is the reverse.
    """
    by_call = tuple(
        statement.text
        for statement in data_statements(source, revision=revision)
        if CONFLICTS_TABLE in statement.text and SERIES_COLUMN in statement.text
    )
    return by_call + writes_naming(source, table=CONFLICTS_TABLE)


class TestNoRevisionFillsTheSeriesIn:
    def test_the_call_reading_finds_the_data_writes_the_chain_already_holds(self) -> None:
        # The control. Four revisions in this chain write rows, and a reading that found none of
        # them would report the absence below whatever any revision did.
        found = {
            statement.revision
            for revision, source in revision_sources().items()
            for statement in data_statements(source, revision=revision)
        }

        assert len(revision_sources()) > REVISIONS_FLOOR
        assert {
            "0004_plan_storage.py",
            "0005_oauth_authorization_server.py",
            "0042_pending_proposal_weight_set.py",
            "0061_rejection_total.py",
        } <= found

    def test_the_call_reading_resolves_the_backfill_the_chain_already_holds(self) -> None:
        # The reading has to name a TABLE and a COLUMN, not just find a call, and the chain's own
        # backfill is the case that proves it: it derives a count from a list the row already
        # carries. That is the shape this column cannot take, because the value it would need is on
        # an anchor row the projection horizon has already deleted.
        rejections = revision_sources()["0061_rejection_total.py"]

        (statement,) = data_statements(rejections, revision="0061")

        assert "UPDATE calendar_sources SET rejected_total" in statement.text

    def test_the_text_reading_finds_a_statement_naming_its_table_literally(self) -> None:
        # The same control for the second reading, on the revision that spells one: the two readings
        # cover different shapes, and this is the shape the call reading resolves to a bare name.
        slots = revision_sources()["0042_pending_proposal_weight_set.py"]

        assert writes_naming(slots, table="pending_proposals")
        assert writes_naming(slots, table=CONFLICTS_TABLE) == ()

    def test_the_text_reading_does_not_read_the_tables_the_chain_creates(self) -> None:
        # `create_table("conflicts", ...)` is DDL. An under-anchored pattern reported it as a write,
        # which would have made the assertion below fail on the revision that made the table.
        made = revision_sources()["0004_plan_storage.py"]

        assert 'create_table(\n        "conflicts"' in made
        assert writes_naming(made, table=CONFLICTS_TABLE) == ()

    @pytest.mark.parametrize(
        "synthetic",
        [
            pytest.param(A_SYNTHETIC_BACKFILL, id="spelled-as-sql"),
            pytest.param(A_SYNTHETIC_TABLE_BACKFILL, id="built-over-a-named-table"),
        ],
    )
    def test_a_synthetic_backfill_is_a_finding_under_one_reading_or_the_other(
        self, synthetic: str
    ) -> None:
        assert fills_the_series_in(synthetic, revision="synthetic")

    def test_no_revision_in_the_chain_fills_the_conflict_series_in(self) -> None:
        found = {
            revision: fills_the_series_in(source, revision=revision)
            for revision, source in revision_sources().items()
        }

        assert {revision: hits for revision, hits in found.items() if hits} == {}


# --------------------------------------------------------------------------------
# Nothing fills an old row in: the application
# --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Site:
    """One place in the shipped tree that puts a value in a ``series_uid`` column."""

    module: str
    scope: str
    written: str


def shipped_modules() -> Mapping[str, Path]:
    """Every Python file this repository ships. Tests are not shipped."""
    root = repository_root()
    found: dict[str, Path] = {}
    for shipped in SHIPPED_ROOTS:
        for source_root in sorted(root.glob(shipped)):
            for path in sorted(source_root.rglob("*.py")):
                found[str(path.relative_to(root))] = path
    return found


def column_writes(source: str, *, module: str, models: frozenset[str]) -> tuple[Site, ...]:
    """Every site here that writes ``series_uid`` as a COLUMN rather than as a value in memory.

    Three shapes, which are the three ways this repository stores a row: a mapping key, a
    ``values()`` keyword, and a mapped class constructed with the field. ``models`` is what
    separates the third from an ordinary dataclass carrying the same field name, and it is derived
    from the tree rather than declared, so a new model mapping this column is covered by arriving.
    """
    found: list[Site] = []
    for node, scope in _scoped(source):
        if isinstance(node, ast.Dict):
            found.extend(
                Site(module, scope, ast.unparse(value))
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and key.value == SERIES_COLUMN
            )
        if not isinstance(node, ast.Call):
            continue
        writes_a_row = (isinstance(node.func, ast.Attribute) and node.func.attr == "values") or (
            isinstance(node.func, ast.Name) and node.func.id in models
        )
        if not writes_a_row:
            continue
        found.extend(
            Site(module, scope, ast.unparse(keyword.value))
            for keyword in node.keywords
            if keyword.arg == SERIES_COLUMN
        )
    return tuple(found)


def models_mapping_the_column(source: str) -> tuple[str, ...]:
    """Every ORM class here that maps ``series_uid`` to a column of its own table."""
    return tuple(
        node.name
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Base" for base in node.bases)
        and any(
            isinstance(field, ast.AnnAssign)
            and isinstance(field.target, ast.Name)
            and field.target.id == SERIES_COLUMN
            and isinstance(field.value, ast.Call)
            and isinstance(field.value.func, ast.Name)
            and field.value.func.id == "mapped_column"
            for field in node.body
        )
    )


def _scoped(source: str) -> Iterator[tuple[ast.AST, str]]:
    """Every node of this source, paired with the dotted class-and-function it sits inside."""
    yield from _within(ast.parse(source), "")


def _within(node: ast.AST, scope: str) -> Iterator[tuple[ast.AST, str]]:
    for child in ast.iter_child_nodes(node):
        nested = scope
        if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            nested = f"{scope}.{child.name}" if scope else child.name
        yield child, nested
        yield from _within(child, nested)


class TestTheRaiseIsWhereTheColumnIsFilled:
    def test_the_walk_reads_the_shipped_tree(self) -> None:
        found = shipped_modules()

        assert len(found) > MODULES_FLOOR
        assert "packages/syncr-api/src/syncr_api/plans/conflicts.py" in found
        assert not [module for module in found if "/tests/" in module]

    def test_the_models_that_map_the_column_are_derived_from_the_tree(self) -> None:
        # Two tables carry this column: the anchors the feed publishes, and the conflicts a raise
        # retains. The census below reads constructor writes against this set, so a set that had
        # quietly emptied would report one shape of write as absent everywhere.
        assert declared_models() == frozenset({"Anchor", "PlanConflict"})

    def test_the_model_reading_tells_a_mapped_class_from_a_dataclass(self) -> None:
        # Both directions, because this is the reading the constructor shape depends on. A record
        # carrying the same field name is a value the process holds, and a mapped column is a row.
        mapped = (
            "class Later(Base, TenantScoped):\n"
            "    series_uid: Mapped[str | None] = mapped_column(String(512), nullable=True)\n"
        )
        in_memory = (
            "@dataclass\nclass Later:\n    series_uid: str | None = None\n"
            "class Also(Base):\n    title: Mapped[str] = mapped_column(String(1))\n"
        )

        assert models_mapping_the_column(mapped) == ("Later",)
        assert models_mapping_the_column(in_memory) == ()

    def test_the_reading_sees_all_three_shapes_of_a_synthetic_write(self) -> None:
        synthetic = (
            "def later():\n"
            '    stored = {"series_uid": "in-a-mapping"}\n'
            '    update(Row).values(series_uid="in-a-values-call")\n'
            '    return PlanConflict(series_uid="in-a-model"), stored\n'
        )

        found = column_writes(synthetic, module="synthetic", models=declared_models())

        assert [site.written for site in found] == [
            "'in-a-mapping'",
            "'in-a-values-call'",
            "'in-a-model'",
        ]

    def test_every_site_that_writes_the_column_is_declared(self) -> None:
        # The whole shipped tree rather than the modules that name the conflicts model, so a new
        # writer is visible wherever it is written. The row a repetition is grouped by is written in
        # exactly one place, and it is the raise: nothing fills the column in afterwards, which is
        # what makes an old row's null permanent until a raise records a new week.
        assert column_write_sites() == DECLARED_COLUMN_WRITES


def declared_models() -> frozenset[str]:
    """Every mapped class in the shipped tree that maps the column, by name."""
    return frozenset(
        name
        for path in shipped_modules().values()
        for name in models_mapping_the_column(path.read_text(encoding="utf-8"))
    )


def column_write_sites() -> frozenset[tuple[str, str, str]]:
    models = declared_models()
    return frozenset(
        (site.module, site.scope, site.written)
        for module, path in shipped_modules().items()
        for site in column_writes(path.read_text(encoding="utf-8"), module=module, models=models)
    )


# Three sites, and the split is the whole point: two write an ANCHOR row, which is where the value
# comes from, and one writes a CONFLICT row, which is the raise copying it across at the instant the
# overlap is recorded. Nothing updates a conflict row's copy afterwards.
DECLARED_COLUMN_WRITES: Final = frozenset(
    {
        (
            "packages/syncr-api/src/syncr_api/anchors/repository.py",
            "AnchorRepository.create",
            "series_uid",
        ),
        (
            "packages/syncr-api/src/syncr_api/anchors/repository.py",
            "AnchorRepository.update_fact",
            "series_uid",
        ),
        (
            "packages/syncr-api/src/syncr_api/plans/conflicts.py",
            "PlanConflictRepository._row",
            "None if commitment is None else commitment.series_uid",
        ),
    }
)


# --------------------------------------------------------------------------------
# Why the surviving anchors are the recent ones
# --------------------------------------------------------------------------------


class _OneWriteTarget:
    """A stand-in for the source repository, holding one row and answering no other question."""

    def __init__(self, target: CalendarSourceRecord | None) -> None:
        self._target = target

    async def write_target(self) -> CalendarSourceRecord | None:
        return self._target


def sources(target: CalendarSourceRecord | None) -> CalendarSourceRepository:
    return _OneWriteTarget(target)  # type: ignore[return-value]  # a fake over the read it makes


class TestTheExpansionIsReadForwardFromNow:
    async def test_the_ingest_horizon_starts_at_now(self) -> None:
        # The mechanism the first declined reason rests on. The span recurrence is expanded over
        # begins at now, so an occurrence that has ended is not published, reconciliation deletes
        # it, and the rows a backfill could still fill are the recent ones. A lower bound that
        # reached backwards would leave old anchors alive and the reason would need restating.
        horizon = await read_ingest_horizon(sources(None), now=NOW)

        assert horizon.start == NOW
        assert horizon.end == NOW + timedelta(days=HORIZON_DAYS_DEFAULT)

    async def test_a_configured_horizon_moves_the_far_end_and_not_the_near_one(self) -> None:
        # The widest a tenant can configure. It is what bounds the fillable window: a row whose
        # anchor still exists names an occurrence inside this span, so the weeks a backfill could
        # supply are bounded ahead of now and never behind it.
        widest = a_write_target(horizon_days=HORIZON_DAYS_MAX)

        horizon = await read_ingest_horizon(sources(widest), now=NOW)

        assert horizon.start == NOW
        assert horizon.end == NOW + timedelta(days=HORIZON_DAYS_MAX)


def a_write_target(*, horizon_days: int) -> CalendarSourceRecord:
    """The one source whose stored horizon every consumer of the figure reads."""
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=ICS,
        role=WRITE_TARGET,
        display_name="University timetable",
        external_id="https://example.ac.uk/timetable.ics",
        included=True,
        horizon_days=horizon_days,
        created_at=NOW,
        sync_state=SyncStateRecord(),
    )
