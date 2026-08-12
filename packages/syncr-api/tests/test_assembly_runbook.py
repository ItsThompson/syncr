"""The assembly runbook's figures and queries, crossed against what decides them.

An operator reads this file once, under pressure, and pastes every query in it. A query that groups
by a label its family does not declare returns one meaningless series, and the table that interprets
it then cannot be wrong in a way the reader can see: it reads as "no repository dominates" forever.
So each grouping label is asserted against the family that declares it, each series against the
histogram that registers it, each figure against the constant that produces it, and each cited file
against the tree.

The read list is the part most likely to rot, because it mirrors a pipeline rather than a constant.
It is asserted in order against the assembler's own source, and its multiset is asserted a second
time against the reading `test_week_assembler.py` counts the reads with, so a walk here that drops
or duplicates a read fails rather than agreeing with itself.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections import Counter
from pathlib import Path
from typing import Final

import pytest

from syncr_api.core.db import MAX_OVERFLOW, POOL_SIZE, POOL_TIMEOUT_SECONDS
from syncr_api.horizon import maintainer as maintainer_module
from syncr_api.horizon.config import MaintainerDuty
from syncr_api.plans import assembler as assembler_module
from syncr_api.plans import injection as injection_module
from syncr_api.plans import placements as placements_module
from syncr_api.plans.assembler import (
    REPOSITORY_READ_COUNT,
    RESOLUTION_COUNT,
    AssemblyCaller,
    WeekAssembler,
)
from tests.repository_census import reads as defined_reads
from tests.repository_census import repository_classes
from tests.test_alert_rules import (
    base_family,
    comparison_on,
    declared_labelnames,
    exported_families,
    families_in,
    repo_root,
)
from tests.test_alert_rules import named as alert_named
from tests.test_week_assembler import _awaited_collaborators

RUNBOOK: Final = Path("docs/runbooks/assembly-slow.md")

# The rule this runbook is the procedure for, and the family its threshold bounds. Both figures the
# file is named after are read out of the rule rather than restated here.
ALERT: Final = "AssemblySlow"
ASSEMBLY_FAMILY: Final = "syncr_assembly_duration_seconds"

# Read from the wiring rather than from the constructor's annotations, because an annotation names a
# Protocol and the histogram's `repository` label carries the concrete class name.
FACTORY: Final = "build_week_assembler"

# A collaborator the read histogram registers no series for, and why. The histogram is installed by
# the scoped repository base, so a collaborator that composes other repositories or answers from
# memory has none of its own, and a row nobody can grep has to say so rather than look like the
# rest.
NO_SERIES_OF_ITS_OWN: Final = {
    "StoredPlacements": "composes repositories that are timed under their own names",
}

# Where a path this runbook cites is resolved from. The prose is written the way the other runbooks
# write it, member-relative or package-relative, so a reader looking for `plans/assembler.py` finds
# it: these are the roots that make such a citation resolvable rather than decorative.
CITATION_ROOTS: Final = (
    Path(),
    Path("packages/syncr-api"),
    Path("packages/syncr-api/src/syncr_api"),
    Path("docs/runbooks"),
)

# A backticked token with one of these suffixes is a citation. Every other backticked token is a
# metric, a label, a constant or a query fragment.
CITED_SUFFIXES: Final = (".md", ".py", ".yml", ".json")

# The week each read of the concession table asks for, and the word the runbook's row has to tell it
# apart with. Two rows carry one series, so prose is the only thing that distinguishes them and a
# swap is invisible to every reading keyed on the series.
CONCESSION_READS: Final = {"preceding": "PRECEDING", "iso_week": "this week"}

_ROW = re.compile(r"^\|\s*\d+\s*\|\s*`([A-Za-z]+)\.([a-z_]+)`\s*\|(.*)\|")
_GROUPING = re.compile(r"sum by \(([^)]*)\) \(rate\((syncr_[a-z_]+)\[")
_CALLER = re.compile(r'caller="([a-z]+)"')
_ASSEMBLY_SELECTOR = re.compile(r'syncr_assembly_duration_seconds_bucket\{caller="([a-z]+)"\}')
_MILLISECONDS = re.compile(r"(\d+) ms\b")
_HOLDS_FOR = re.compile(r"(\d+)([mh])")
_BUDGET = re.compile(r"p95 under (\d+) ms")
_BASIS = re.compile(r"set against a figure of ([a-z]+)")
_WIRED_CALLER = re.compile(r"caller=AssemblyCaller\.([A-Z]+)")
_CITATION = re.compile(r"`([\w./-]+)`")
_ASSEMBLIES_A_DAY = re.compile(r"roughly (\d+) assemblies a day")


def read(relative: Path) -> str:
    path = repo_root() / relative
    assert path.is_file(), f"{relative} does not exist"
    return path.read_text(encoding="utf-8")


def one_line(text: str) -> str:
    """The text with every run of whitespace collapsed, which is how a wrapped query reads."""
    return re.sub(r"\s+", " ", text)


def listed_reads(text: str) -> list[tuple[str, str]]:
    """The ``Class.method`` pairs the runbook's table lists, in the order it lists them."""
    return [(name, method) for name, method, _ in listed_rows(text)]


def listed_rows(text: str) -> list[tuple[str, str, str]]:
    """Every row of the read table: the class, the method, and what the row says it resolves."""
    return [
        (found.group(1), found.group(2), found.group(3).strip())
        for found in (_ROW.match(line) for line in text.splitlines())
        if found is not None
    ]


def awaited_reads(source: str, *, method: str) -> list[tuple[str, str]]:
    """Every ``await self._x.y()`` one method performs, in textual order.

    An await of the class's own method is returned under the empty collaborator name rather than
    dropped, because the reads it performs happen where it is called.
    """
    found: list[tuple[int, int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name != method:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Await) or not isinstance(inner.value, ast.Call):
                continue
            call = inner.value
            if not isinstance(call.func, ast.Attribute):
                continue
            owner = call.func.value
            if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name):
                found.append((inner.lineno, inner.col_offset, owner.attr, call.func.attr))
            elif isinstance(owner, ast.Name) and owner.id == "self":
                found.append((inner.lineno, inner.col_offset, "", call.func.attr))
    return [(name, called) for _, _, name, called in sorted(found)]


def reads_in_order(service: type) -> list[tuple[str, str]]:
    """The series one assembly reads, in the order it reads them.

    A helper of the service is spliced in at its own call site: it is defined below the method that
    awaits it, so an order keyed on the line number alone reports its reads last.
    """
    source = inspect.getsource(service)
    wired = wired_classes()
    ordered: list[tuple[str, str]] = []
    for name, called in awaited_reads(source, method="_assemble"):
        if not name:
            ordered.extend(
                (wired[held], method) for held, method in awaited_reads(source, method=called)
            )
            continue
        ordered.append((wired[name], called))
    return ordered


def wired_classes() -> dict[str, str]:
    """What production constructs for each of the assembler's collaborators.

    A keyword passed a local name is resolved through that name's own assignment, which is how one
    repository comes to be shared by two collaborators and read twice in one assembly.
    """
    tree = ast.parse(inspect.getsource(injection_module))
    factory = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == FACTORY
    )
    assigned = {
        target.id: node.value.func.id
        for node in ast.walk(factory)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
        for target in node.targets
        if isinstance(target, ast.Name) and isinstance(node.value.func, ast.Name)
    }
    wired: dict[str, str] = {}
    for node in ast.walk(factory):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            value = keyword.value
            if keyword.arg is None:
                continue
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                wired[f"_{keyword.arg}"] = value.func.id
            elif isinstance(value, ast.Name) and value.id in assigned:
                wired[f"_{keyword.arg}"] = assigned[value.id]
    assert wired, f"{FACTORY} constructs nothing this can read, so every row below looks wrong"
    return wired


def registered_series() -> set[tuple[str, str]]:
    """Every ``{repository, method}`` pair the read histogram registers, discovered per class."""
    return {(cls.__name__, method) for cls in repository_classes() for method in defined_reads(cls)}


def groupings(text: str) -> list[tuple[str, frozenset[str]]]:
    """Every family this text groups a rate over, with the labels it groups by."""
    return [
        (base_family(found.group(2)), frozenset(found.group(1).replace(" ", "").split(",")))
        for found in _GROUPING.finditer(one_line(text))
    ]


def unresolvable_citations(text: str) -> list[str]:
    """Every file the text cites that no declared root resolves.

    A token counts as a citation when it carries a directory or names a document, which is how the
    other runbooks write one. A bare module name is not read: admitting one would make every
    backticked word with a dot in it a path, and this file cites none that way.
    """
    cited = [
        found
        for found in _CITATION.findall(text)
        if found.endswith(CITED_SUFFIXES) and ("/" in found or found.endswith(".md"))
    ]
    return [
        one
        for one in cited
        if not any((repo_root() / root / one).is_file() for root in CITATION_ROOTS)
    ]


def wired_callers() -> set[str]:
    """Every caller some module actually assembles under, read from the source."""
    source = repo_root() / "packages" / "syncr-api" / "src" / "syncr_api"
    found = {
        member
        for path in source.rglob("*.py")
        for member in _WIRED_CALLER.findall(path.read_text(encoding="utf-8"))
    }
    assert found, "nothing names a caller, so every selector in the runbook would look wired"
    return {AssemblyCaller[member].value for member in found}


def caller_the_maintainer_assembles_under() -> str:
    """The label value the maintainer's own assemblies carry, read from the maintainer."""
    found = set(_WIRED_CALLER.findall(inspect.getsource(maintainer_module)))

    assert len(found) == 1, f"the maintainer names {sorted(found)} callers, and the runbook one"
    return AssemblyCaller[found.pop()].value


def caller_the_alert_is_scoped_to() -> str:
    """The series the rule this runbook belongs to reads, taken from the rule's own expression."""
    found: set[str] = set(_ASSEMBLY_SELECTOR.findall(alert_named("AssemblySlow").expr))

    assert len(found) == 1, f"the rule selects {sorted(found)} callers, and the runbook one"
    return found.pop()


def assemblies_a_day() -> int:
    """The maintainer's own figure for how many assemblies its second duty performs in a day."""
    found = _ASSEMBLIES_A_DAY.search(MaintainerDuty.__doc__ or "")

    assert found is not None, "the maintainer's duty no longer states the figure the runbook quotes"
    return int(found.group(1))


def milliseconds_the_rule_bounds() -> int:
    """The rule's threshold as the runbook writes it, which is milliseconds."""
    return round(comparison_on(alert_named(ALERT), ASSEMBLY_FAMILY).threshold * 1000)


def wait_in_minutes(holds_for: str) -> int:
    """The rule's ``for:`` as minutes, which is how a runbook states a wait."""
    found = _HOLDS_FOR.fullmatch(holds_for)

    assert found is not None, f"the rule waits {holds_for!r}, which this cannot read as minutes"
    return int(found.group(1)) * (60 if found.group(2) == "h" else 1)


def budgeted_milliseconds() -> int:
    """The assembly's own p95 budget, read from the pipeline that states it."""
    found = _BUDGET.search(one_line(assembler_module.__doc__ or ""))

    assert found is not None, "the pipeline no longer states the budget the runbook quotes"
    return int(found.group(1))


def the_count_the_budget_was_set_against() -> str:
    """The figure the pipeline records the budget and the alert as having been calibrated to."""
    found = _BASIS.search(one_line(assembler_module.__doc__ or ""))

    assert found is not None, "the pipeline no longer records what the budget was set against"
    return found.group(1)


def concession_reads() -> list[str]:
    """The week each read of the repeated collaborator asks for, in the order the assembly asks.

    Read from the argument at the call site, because the two reads are one series and one method:
    nothing but the argument distinguishes the week being assembled from the week before it.
    """
    held = wired_classes()
    repeated = repeated_reads()
    asked: list[tuple[int, int, str]] = []
    for node in ast.walk(ast.parse(inspect.getsource(WeekAssembler))):
        if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        owner = call.func
        if not isinstance(owner, ast.Attribute) or not isinstance(owner.value, ast.Attribute):
            continue
        if (held.get(owner.value.attr), owner.attr) not in repeated:
            continue
        argument = ast.unparse(call.args[0]) if call.args else ""
        asked.append((node.lineno, node.col_offset, argument))

    assert asked, "no collaborator is read twice, so the runbook has no pair to tell apart"
    return [argument for _, _, argument in sorted(asked)]


def repeated_reads() -> set[tuple[str, str]]:
    """Every series one assembly reads more than once."""
    return {pair for pair, count in Counter(reads_in_order(WeekAssembler)).items() if count > 1}


class TestTheFiguresItQuotes:
    """Every number in the file, against the thing that decides it."""

    def test_it_states_the_threshold_and_the_wait_the_rule_declares(self) -> None:
        """The figures the file is named after, which a retune of the rule moves.

        The rule and its crossing hold the threshold to one spelling between themselves, and this
        file states it four more times: the title, the trigger block, the heading and the prose. A
        retune that reddens the rule's own crossing, is fixed there and ships leaves an operator
        reading the retired number under pressure.
        """
        rule = alert_named(ALERT)
        bound = comparison_on(rule, ASSEMBLY_FAMILY)
        runbook = read(RUNBOOK)

        assert f"{bound.operator} {bound.threshold}" in one_line(runbook)
        assert f"**{wait_in_minutes(rule.holds_for)} minutes**" in runbook

    def test_every_millisecond_figure_it_states_is_one_the_tree_produces(self) -> None:
        """The two figures in milliseconds, as an exact set, so a fourth copy cannot drift alone.

        The threshold appears in the title, the heading and the prose, and the assembly's own budget
        twice more. Stated as an equality rather than a containment: a copy that drifts fails, and
        so does a figure this crossing has no producer for.
        """
        stated = {int(one) for one in _MILLISECONDS.findall(read(RUNBOOK))}

        assert stated == {milliseconds_the_rule_bounds(), budgeted_milliseconds()}

    def test_it_states_the_read_count_the_two_figures_were_set_against(self) -> None:
        """The basis, which is not the count today and is why the threshold is not derived."""
        basis = the_count_the_budget_was_set_against()

        assert f"set against {basis} repository reads" in read(RUNBOOK)

    def test_it_states_the_resolution_and_read_counts_the_assembler_declares(self) -> None:
        runbook = read(RUNBOOK)

        assert f"**{RESOLUTION_COUNT}** resolutions" in runbook
        assert f"**{REPOSITORY_READ_COUNT}** repository reads" in runbook

    def test_it_states_the_pool_bound_the_engine_is_built_with(self) -> None:
        """Pool exhaustion presents as a slow read, so the ceiling has to be the engine's own."""
        runbook = read(RUNBOOK)

        assert f"**{POOL_SIZE + MAX_OVERFLOW}** connections" in runbook
        assert f"`POOL_SIZE` {POOL_SIZE} plus `MAX_OVERFLOW` {MAX_OVERFLOW}" in runbook
        assert f"**{POOL_TIMEOUT_SECONDS} seconds**" in runbook

    def test_it_states_the_maintainers_own_figure_for_its_cadence(self) -> None:
        assert f"**{assemblies_a_day()} times a day**" in read(RUNBOOK)


class TestTheReadsItLists:
    """The ordered list, which is the answer to "which read is the regression"."""

    def test_it_lists_every_read_in_the_order_the_assembly_performs_them(self) -> None:
        assert listed_reads(read(RUNBOOK)) == reads_in_order(WeekAssembler)

    def test_the_list_holds_as_many_reads_as_the_assembler_declares(self) -> None:
        assert len(listed_reads(read(RUNBOOK))) == REPOSITORY_READ_COUNT

    def test_the_reads_it_lists_are_the_ones_the_count_guard_counts(self) -> None:
        """The control for the walk above, against the reading the count is guarded with.

        That reading is unordered and this one is not, so a splice or a sort that dropped a read
        would agree with itself here and disagree with the figure the budget rests on.
        """
        wired = wired_classes()
        counted = Counter(wired[name] for name in _awaited_collaborators(WeekAssembler))

        assert Counter(name for name, _ in listed_reads(read(RUNBOOK))) == counted

    def test_every_row_is_a_series_the_read_histogram_registers_or_says_it_is_not(self) -> None:
        """A row an operator cannot find in the panel is worse than no row.

        Stated as an exact equality over the declared exceptions, so a collaborator that stops
        registering a series fails here rather than becoming a row nobody can grep.
        """
        listed = listed_reads(read(RUNBOOK))
        registered = registered_series()

        assert {name for name, method in listed if (name, method) not in registered} == set(
            NO_SERIES_OF_ITS_OWN
        )

    @pytest.mark.parametrize("name", sorted(NO_SERIES_OF_ITS_OWN))
    def test_the_runbook_says_the_exempt_row_carries_no_series(self, name: str) -> None:
        """The other edge: an operator hunting the panel for a row that is not in it.

        Read per bullet rather than per file, because the class name is in the table too and a
        reading over the whole file would be satisfied by the row it is meant to qualify.
        """
        bullets = re.split(r"\n- ", read(RUNBOOK))

        assert any(f"`{name}`" in one and "no series" in one for one in bullets), (
            f"no bullet says {name} carries no series, so the panel's silence looks like a gap"
        )

    def test_the_two_reads_of_one_table_are_told_apart_the_way_the_code_orders_them(self) -> None:
        """One series appears twice, so prose is all that tells the two rows apart.

        Keyed on the argument each call passes, so swapping the two descriptions fails: every other
        reading here is keyed on the series, and a swap leaves the series list, the multiset, the
        count and the exclusion all intact while telling the operator the opposite of the code.
        """
        asked = concession_reads()
        described = [
            description
            for name, method, description in listed_rows(read(RUNBOOK))
            if (name, method) in repeated_reads()
        ]

        assert len(described) == len(asked), (
            f"{len(asked)} reads of one series, and {len(described)} rows for it"
        )
        for week, description in zip(asked, described, strict=True):
            assert week in CONCESSION_READS, (
                f"the code reads the table for {week!r}, which nothing here can tell a row apart by"
            )
            expected = CONCESSION_READS[week]
            others = {word for key, word in CONCESSION_READS.items() if key != week}

            assert expected in description, f"the row for {week} does not say {expected!r}"
            assert not any(word in description for word in others), (
                f"the row for {week} also says {sorted(others)}, so the pair cannot be told apart"
            )

    def test_the_reading_sees_a_row_of_the_table(self) -> None:
        """The positive control for the row reading, over the shape the file writes."""
        table = "| 4 | `PlanRepository.latest_approved` | the churn baseline |\nnot a row\n"

        assert listed_reads(table) == [("PlanRepository", "latest_approved")]

    def test_the_seam_that_carries_no_series_is_the_one_with_four_statements(self) -> None:
        """The four statements are named in the file, because the panel shows them and not it.

        The classes come from the seam's own annotations rather than from a wiring reading: it is
        constructed positionally and its parameters are concrete, so an annotation here IS the
        label. A seam that adopted Protocols would fail loudly at the lookup below.
        """
        runbook = read(RUNBOOK)
        wired = wired_classes()
        behind = awaited_reads(
            inspect.getsource(getattr(placements_module, wired["_placements"])), method="read"
        )
        annotations = inspect.signature(getattr(placements_module, wired["_placements"])).parameters

        assert behind, "the placement seam awaits nothing, so the runbook's four are stale"
        for held, method in behind:
            cls = annotations[held.removeprefix("_")].annotation
            assert f"`{cls}.{method}`" in runbook, f"{cls}.{method} is behind the seam and unnamed"


class TestTheQueriesItTellsYouToPaste:
    """A query with a label its family does not carry is the failure this file exists over."""

    def test_every_label_it_groups_by_is_one_the_family_declares(self) -> None:
        declared = declared_labelnames()
        found = groupings(read(RUNBOOK))

        assert found, "no query groups a rate, so this crossing asserts nothing"
        for family, labels in found:
            assert family in declared, f"{family} is not a family this workspace declares"
            undeclared = labels - declared[family] - {"le"}
            assert undeclared == frozenset(), (
                f"{family} does not declare {sorted(undeclared)}, so grouping by it collapses "
                f"every series into one that carries the label as the empty string"
            )

    def test_every_family_it_names_is_one_the_deployment_exports(self) -> None:
        """A `syncr_`-prefixed token that is not a family, a container name for instance, would trip
        this on a correct edit. The file holds none today, and the trip-wire is the accepted cost of
        reading the prose as well as the queries."""
        named = families_in(read(RUNBOOK))

        assert named, "the runbook names no family, so an operator has nothing to paste"
        assert named <= exported_families(), (
            f"{sorted(named - exported_families())} is named here and exported by nothing"
        )

    def test_every_caller_it_selects_is_one_some_module_assembles_under(self) -> None:
        selected = set(_CALLER.findall(read(RUNBOOK)))

        assert selected, "the runbook selects no caller, and the alert is scoped to one"
        assert selected <= wired_callers(), (
            f"{sorted(selected - wired_callers())} is selected here and assembled under by nothing"
        )

    def test_the_background_comparison_selects_the_caller_the_maintainer_wires(self) -> None:
        """The comparison is the maintainer's, so it has to read the maintainer's own series.

        Keyed on the selectors its queries carry rather than on the file, because the prose names
        the maintainer's label too: a substring reading of the whole file passes while the query
        beside it reads a different series, which is what this file shipped.
        """
        selected = set(_ASSEMBLY_SELECTOR.findall(one_line(read(RUNBOOK))))

        assert selected == {
            caller_the_alert_is_scoped_to(),
            caller_the_maintainer_assembles_under(),
        }

    def test_the_reading_sees_a_grouping_over_a_wrapped_query(self) -> None:
        """The positive control. The file wraps its queries, so a line-oriented read sees none."""
        family = "syncr_db_query_duration_seconds"
        wrapped = (
            "topk(5, histogram_quantile(0.99,\n"
            f"  sum by (le, repository, method) (rate({family}_bucket[30m]))))"
        )

        assert groupings(wrapped) == [(family, frozenset({"le", "repository", "method"}))]

    def test_the_reading_sees_a_label_no_family_declares(self) -> None:
        """The other edge: the grouping this file shipped, which read one empty-labelled series."""
        was = "sum by (le, repository) (rate(syncr_method_duration_seconds_bucket[30m]))"

        (family, labels), *rest = groupings(was)
        assert rest == []
        assert labels - declared_labelnames()[family] - {"le"} == frozenset({"repository"})


class TestTheFilesItCites:
    """A pointer an operator cannot open is worse than no pointer."""

    def test_every_file_it_cites_resolves_in_this_repository(self) -> None:
        assert unresolvable_citations(read(RUNBOOK)) == []

    def test_the_reading_sees_a_citation_that_resolves(self) -> None:
        """The positive control, keyed on a path this repository holds under a declared root."""
        assert unresolvable_citations("see `plans/assembler.py` and `probe-slow.md`") == []

    def test_the_reading_sees_a_document_this_repository_does_not_hold(self) -> None:
        """The other edge: the citation this file shipped, into a document nobody here can open."""
        assert unresolvable_citations("the budget from `19-nonfunctional.md`") == [
            "19-nonfunctional.md"
        ]
