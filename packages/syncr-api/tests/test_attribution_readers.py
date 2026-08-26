"""Every production reader of the attribution table, enumerated from the tree rather than assumed.

``syncr_domain.outcomes.attributed_span`` is the one statement of what a block contributes to the
content it holds. A placement has two readings and they exist for opposite reasons: the time it
occupies, which no outcome changes, and the time it attributes, which an outcome decides. The
placement index tells them apart with an injected strategy rather than with a branch, and its
register says which quantity takes which.

The subject of this file is the word EVERY. A case written over a reader set somebody listed cannot
fail on the reader they forgot, so every set here is derived from the source on every run and then
compared against a declared register:

1. the modules whose code reaches the table, walked over every package's shipped source
2. the modules naming each identifier the attributed span travels under below the table, because a
   consumer can net it without ever naming the table: one reading of the placement index and one
   return type hand it out, and reaching either takes an import
3. the placement index's public readings and the span each one takes, read out of the index's own
   constructor

Each derivation is also run against a synthetic source that breaks it, because a derivation that
reports nothing agrees with every register it is compared against.

The walk measures the checkout this file sits in. Nothing here believes a measurement until the
imported package is confirmed to be that checkout's, because a walk over one tree and an assertion
against another tree's behaviour is two answers presented as one.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

import syncr_api
import syncr_domain
from syncr_api.plans.netting import PlacedTime, placements
from syncr_api.plans.records import BlockOutcomeRecord
from syncr_api.reviews.coverage import ReviewedDay, confirmed_coverage
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.outcomes import MISS_STATE, RecordedOutcome
from tests.assembly_fakes import MINUTES_PER_HOUR, NOW, a_plan, a_task_block, at, between

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from syncr_domain.plan import Block

THE_TABLE = "attributed_span"

# The modules whose code reaches the table, compared against the walk below on every run. Two, and
# they net different things from one answer: a placement's contribution to its task, and the minutes
# a confirmed day gives an Area. Every member also needs a case in `ATTRIBUTION_BY_MODULE`, so a
# module added here without one cannot pass either.
MODULES_READING_THE_TABLE = frozenset({"syncr_api.plans.netting", "syncr_api.reviews.coverage"})

# Every identifier the attributed span travels under, and the modules whose code names each. The
# register above covers the table's own callers, and a consumer can net the attributed span without
# ever naming the table: the placement index hands it out through one reading and one return type,
# and reaching either takes an import. So the chain is walked at every link rather than at the top.
MODULES_BY_LINK = {
    "attributed_span": {"syncr_api.plans.netting", "syncr_api.reviews.coverage"},
    "_area_span": {"syncr_api.plans.netting"},
    "_attributed_span": {"syncr_api.plans.netting"},
    "_worked_span": {"syncr_api.plans.netting"},
    # The declaring module is absent because a definition is not a reference, so this row holds the
    # consumers and nothing else.
    "attributed_to_task_before": {"syncr_api.plans.demand"},
    "immovable_minutes_of_area": {"syncr_api.plans.reservations"},
    "AttributedMinutes": {"syncr_api.plans.netting"},
    # Only one of these three reads the field: the other two hold a local of the same name. The row
    # is over identifiers, so a fourth module reddens it whichever way it means the word, and
    # looking at that module is the point.
    "attributed": {
        "syncr_api.plans.demand",
        "syncr_api.plans.netting",
        "syncr_api.reviews.coverage",
    },
}

THE_INDEX = "PlacedTime"

# A reading built from a helper that takes no span argument. No reading of the real index is built
# that way; the synthetic control at the bottom of this file has one, so the derivation still has to
# report it. Named rather than left as `None` so a register row saying it says it in words.
NOT_INJECTED = "not injected"

# The strategies that read what an OUTCOME attributed, as against the time a placement occupies.
# Three of them, because the four consumers of the table clip it differently: the demand clips at
# a deadline and splits at ``now``, an Area's floor reading clips to the span the placement holds,
# the solver's remaining work clips at ``now`` alone, and the Area's placed figure takes the
# outcome's answer for the part behind ``now`` and the placement's own span for the part ahead of
# it -- which is why its strategy is BUILT per index rather than named once.
ATTRIBUTING_SPANS = frozenset({"_attributed_span", "_worked_span", "_area_span"})

# Each public reading of the placement index and the strategy behind the index it reads, compared
# against that index's constructor on every run. All four take the outcome's answer somewhere; no
# reading is left with the own span alone any more, because capacity reads the placements directly
# rather than through this index.
SPAN_BY_READING = {
    "attributed_to_task_before": "_attributed_span",
    "immovable_minutes_of_area": "_worked_span",
    "immovable_minutes_of_task": "_attributed_span",
    "minutes_of_area": "_area_span",
}

A_TASK = uuid4()
CAREER = uuid4()
# Tuesday 09:00-10:00, an hour behind `NOW`, so the hour is past and immovable on every reading.
A_PAST_HOUR = between(9, 10, day=1)
A_DEADLINE = at(9, day=4)
THE_WEEK = Interval(at(0), at(0, day=7))
CONFIRMED_AT = at(23, day=1)


# --------------------------------------------------------------------------------
# The walk, and the two derivations over it
# --------------------------------------------------------------------------------


def repository_root() -> Path:
    """The checkout this file belongs to, which is the tree every derivation below measures."""
    return Path(__file__).resolve().parents[3]


def production_modules(root: Path) -> Mapping[str, Path]:
    """Every package's shipped module, by import path. A test is not a reader, so tests are out."""
    found: dict[str, Path] = {}
    for source_root in sorted(root.glob("packages/*/src")) + sorted(root.glob("cli/src")):
        for path in sorted(source_root.rglob("*.py")):
            found[".".join(path.relative_to(source_root).with_suffix("").parts)] = path
    return found


def modules_using(name: str, modules: Mapping[str, Path]) -> set[str]:
    """The modules whose CODE names ``name``.

    Identifiers only. Three modules contain the string ``attributed_span`` and two name it as code,
    so a text search reports three readers and the module that declares the table is one of them.
    """
    return {
        module
        for module, path in modules.items()
        if name in _names_used(path.read_text(encoding="utf-8"))
    }


def span_by_reading(source: str, *, of: str) -> Mapping[str, str]:
    """Each public reading of class ``of`` and the strategy behind the index it reads.

    Taken from the constructor rather than from a table beside it, so pointing a reading at another
    index, or building an index with the other strategy, changes this answer.
    """
    declared = _class_named(of, source)
    built = _indexes_built_by(declared)
    return {
        member.name: _strategy_behind(member, built)
        for member in declared.body
        if isinstance(member, ast.FunctionDef) and not member.name.startswith("_")
    }


def _names_used(source: str) -> set[str]:
    """Every name this source uses as code, whether referenced directly or through a module."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def _class_named(name: str, source: str) -> ast.ClassDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not a class in this source")


def _indexes_built_by(declared: ast.ClassDef) -> Mapping[str, str]:
    """Each attribute this class assigns from a call, and the span strategy that call injects."""
    built: dict[str, str] = {}
    for node in ast.walk(declared):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                built[target.attr] = _span_argument(node.value)
    return built


def _span_argument(call: ast.Call) -> str:
    for passed in call.keywords:
        if passed.arg == "span":
            value = passed.value
            if isinstance(value, ast.Name):
                return value.id
            # A strategy built per index, parameterised by the instant the reading splits at, is
            # still one strategy: the factory's name is what the register holds it under.
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                return value.func.id
            return NOT_INJECTED
    return NOT_INJECTED


def _strategy_behind(member: ast.FunctionDef, built: Mapping[str, str]) -> str:
    """The one strategy behind the indexes this reading reads.

    A reading answers from one index. Two would make it a reading of two placement sets, which is
    the collapse the injected strategy exists to keep visible, so this reports it rather than
    picking one of them.
    """
    taken = {
        built[node.attr]
        for node in ast.walk(member)
        if isinstance(node, ast.Attribute) and node.attr in built
    }
    if len(taken) != 1:
        raise AssertionError(f"{member.name} reads {sorted(taken)}, which is not one index")
    return taken.pop()


# --------------------------------------------------------------------------------
# What each reader gives a skipped past hour: one block, one row, two readers
# --------------------------------------------------------------------------------


def netting_attribution() -> tuple[int, int]:
    """What the placement index attributes to the task, presumed and then skipped."""
    return (_attributed_to_the_task(skipped=False), _attributed_to_the_task(skipped=True))


def review_attribution() -> tuple[int, int]:
    """What the pie review's numerator gives the Area, presumed and then skipped."""
    return (_given_to_the_area(skipped=False), _given_to_the_area(skipped=True))


ATTRIBUTION_BY_MODULE: Mapping[str, Callable[[], tuple[int, int]]] = {
    "syncr_api.plans.netting": netting_attribution,
    "syncr_api.reviews.coverage": review_attribution,
}


def _a_past_hour_of_career_work() -> Block:
    return a_task_block(task_id=A_TASK, area_id=CAREER, interval=A_PAST_HOUR)


def _attributed_to_the_task(*, skipped: bool) -> int:
    block = _a_past_hour_of_career_work()
    recorded = [RecordedOutcome(binding=block.binding, state=MISS_STATE)] if skipped else []
    placed = PlacedTime(placements(a_plan(blocks=[block]), (), now=NOW, outcomes=recorded), now=NOW)
    return placed.attributed_to_task_before(A_TASK, A_DEADLINE).past


def _given_to_the_area(*, skipped: bool) -> int:
    block = _a_past_hour_of_career_work()
    day = ReviewedDay(
        on=A_PAST_HOUR.start.date(),
        span=Interval(at(0, day=1), at(0, day=2)),
        blocks=(block,),
        confirmed_at=CONFIRMED_AT,
        is_off_plan=False,
    )
    recorded = {str(block.id): _a_recorded_skip(block)} if skipped else {}
    covered = confirmed_coverage([day], outcomes=recorded, within=THE_WEEK, off_plan=IntervalSet())
    found = covered.get(CAREER)
    return 0 if found is None else found.total_minutes()


def _a_recorded_skip(block: Block) -> BlockOutcomeRecord:
    return BlockOutcomeRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        block_id=block.id,
        binding=block.binding,
        revision_id=uuid4(),
        state=MISS_STATE,
        actual_minutes=None,
        actual_interval=None,
        occurred_at=block.interval.start,
        confirmed_at=CONFIRMED_AT,
    )


# --------------------------------------------------------------------------------
# Rule 1: the walk measures this checkout, and it found something to measure
# --------------------------------------------------------------------------------


def test_the_walk_measures_the_checkout_whose_behaviour_this_file_asserts() -> None:
    # The control for every derivation here. The walk resolves a tree from this file's own path
    # while the assertions below run imported code, so a run against a scratch copy of the tree
    # could otherwise derive one answer from the copy and measure the other from the original.
    # Both packages, because the table is declared in one and every reader of it is in the other.
    root = repository_root()

    imported = {package.__name__: package.__file__ for package in (syncr_api, syncr_domain)}

    elsewhere = {
        name: found
        for name, found in imported.items()
        if found is None or not Path(found).resolve().is_relative_to(root)
    }
    assert elsewhere == {}, (
        f"{elsewhere} is imported from outside {root}, so the walk over that tree and the "
        "behaviour asserted below are answers about two different checkouts"
    )


def test_the_walk_finds_each_packages_source_and_excludes_its_tests() -> None:
    # The control for the rule below's subject matter: `modules_using` iterates, so it answers the
    # empty set over an empty walk and would agree with a register naming nothing.
    found = production_modules(repository_root())

    assert len(found) > 100
    assert {"syncr_api.plans.netting", "syncr_domain.outcomes", "syncr_solver.inputs"} <= set(found)
    assert not [module for module in found if ".tests." in module or module.startswith("tests.")]


# --------------------------------------------------------------------------------
# Rule 2: the table has exactly the readers the register names
# --------------------------------------------------------------------------------


def test_the_table_is_read_by_exactly_the_modules_this_file_examines() -> None:
    reading = modules_using(THE_TABLE, production_modules(repository_root()))

    assert reading == set(MODULES_READING_THE_TABLE), (
        f"{sorted(reading)} reach the attribution table and "
        f"{sorted(MODULES_READING_THE_TABLE)} are accounted for. A reader nobody enumerated is a "
        "reader no case here can fail on"
    )


def test_the_reader_walk_reports_a_module_that_reaches_the_table_through_its_own_module() -> None:
    # The control. The walk reads identifiers, so it must see the attribute spelling as well as the
    # direct one: a module that imports `outcomes` and calls through it is a reader.
    direct = "from syncr_domain.outcomes import attributed_span\nx = attributed_span(a, b)\n"
    through_the_module = "from syncr_domain import outcomes\nx = outcomes.attributed_span(a, b)\n"
    prose_only = '"""Stated at :func:`syncr_domain.outcomes.attributed_span`."""\n'

    assert THE_TABLE in _names_used(direct)
    assert THE_TABLE in _names_used(through_the_module)
    assert THE_TABLE not in _names_used(prose_only)


@pytest.mark.parametrize("module", sorted(MODULES_READING_THE_TABLE))
def test_each_reader_of_the_table_gives_a_skipped_past_hour_to_nothing(module: str) -> None:
    # One block and one row, read by both. The table has one statement and this is what makes the
    # two readers answer from it rather than each deciding what a skip contributes.
    presumed, skipped = ATTRIBUTION_BY_MODULE[module]()

    assert presumed == MINUTES_PER_HOUR
    assert skipped == 0


def test_every_module_that_reads_the_table_has_a_case_in_this_file() -> None:
    # What stops the case above from being a case over an assumed set: the register is compared
    # against the tree by the rule above, and every member of it is compared against behaviour here.
    assert set(ATTRIBUTION_BY_MODULE) == set(MODULES_READING_THE_TABLE)


# --------------------------------------------------------------------------------
# Rule 3: nothing nets the attributed span without naming one of the links it travels under
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("link", sorted(MODULES_BY_LINK))
def test_each_link_the_attributed_span_travels_under_is_named_by_the_register_it_holds(
    link: str,
) -> None:
    naming = modules_using(link, production_modules(repository_root()))

    assert naming == MODULES_BY_LINK[link], (
        f"{sorted(naming)} name {link!r} and {sorted(MODULES_BY_LINK[link])} are accounted for. "
        "A consumer that nets the attributed span without naming the table reaches it through one "
        "of these links"
    )


def test_the_two_registers_cannot_drift_about_the_tables_own_callers() -> None:
    # The chain's first link and the register the behavioural cases run over answer one question.
    # Two answers to it would let a reader be added to one and stay absent from the other.
    assert MODULES_BY_LINK[THE_TABLE] == set(MODULES_READING_THE_TABLE)


def test_the_chain_register_reports_a_consumer_that_never_names_the_table(tmp_path: Path) -> None:
    # The control, written against the shape it exists for: a module that takes the index's reading
    # and nets the past half without ever naming the table. A register over the table's own callers
    # is blind to it, which is what the second assertion here states.
    planted = tmp_path / "shadow_demand.py"
    planted.write_text(
        "def shadow_demand(placed, task_id, deadline):\n"
        "    return placed.attributed_to_task_before(task_id, deadline).past\n",
        encoding="utf-8",
    )
    walked = {"syncr_api.plans.shadow_demand": planted}

    assert modules_using("attributed_to_task_before", walked) == {"syncr_api.plans.shadow_demand"}
    assert modules_using(THE_TABLE, walked) == set()


# --------------------------------------------------------------------------------
# Rule 4: the placement index's readings take exactly the spans the register names
# --------------------------------------------------------------------------------


def the_index_source() -> str:
    return Path(placements.__code__.co_filename).read_text(encoding="utf-8")


def test_each_reading_of_the_placement_index_takes_the_span_the_register_names() -> None:
    derived = span_by_reading(the_index_source(), of=THE_INDEX)

    assert derived == SPAN_BY_READING, (
        f"{derived} is what the index's constructor injects and {SPAN_BY_READING} is accounted "
        "for. A reading that changed which span it takes changed which placement set it nets"
    )


def test_the_readings_that_take_an_outcomes_answer_are_the_four_that_net_work_done() -> None:
    # The claim the injected strategies exist to make checkable. Collapsing an attributing reading
    # onto the placement's own span is the shape three review iterations of this arithmetic found,
    # and it is invisible from either side alone: each reading is right for its own consumer, and
    # the fourth takes the outcome's answer for only half its question, which is exactly the kind
    # of asymmetry a register over whole readings cannot see and this one spells out instead.
    derived = span_by_reading(the_index_source(), of=THE_INDEX)

    from_the_outcome = {name for name, span in derived.items() if span in ATTRIBUTING_SPANS}

    assert from_the_outcome == set(derived)
    assert set(derived) == set(SPAN_BY_READING)


def test_the_strategy_derivation_reports_a_reading_pointed_at_the_other_index() -> None:
    # The control, over the shape the real class has: two indexes built by one helper with two
    # strategies, one built by a helper that takes none, and an attribute that is not an index.
    synthetic = """
class Indexed:
    def __init__(self, placed, *, now):
        self._now = now
        self._attributed = _by_task(placed, span=_attributed_span)
        self._split = _by_area(placed, span=_area_span(now))
        self._bare = _by_area(placed)

    def attributes(self):
        return self._attributed.get(0)

    def both_halves(self):
        return self._split.get(0)

    def unparameterised(self):
        return self._bare.get(0)
"""
    derived = span_by_reading(synthetic, of="Indexed")

    assert derived == {
        "attributes": "_attributed_span",
        "both_halves": "_area_span",
        "unparameterised": NOT_INJECTED,
    }
    assert derived["attributes"] != derived["both_halves"]


def test_the_strategy_derivation_refuses_a_reading_that_nets_two_placement_sets() -> None:
    # The control for the one branch above that raises. Without it, a reading that answered from
    # both indexes would report whichever strategy the set happened to yield.
    collapsed = """
class Indexed:
    def __init__(self, placed):
        self._attributed = _by_task(placed, span=_attributed_span)
        self._own = _by_task(placed, span=_own_span)

    def both(self):
        return self._attributed.get(0), self._own.get(0)
"""

    with pytest.raises(AssertionError, match="which is not one index"):
        span_by_reading(collapsed, of="Indexed")


def test_the_strategy_derivation_refuses_a_class_the_source_does_not_declare() -> None:
    # The control for the other raising branch. A renamed class would otherwise derive an empty
    # mapping, and an empty mapping compared against a register is a rule that reports nothing.
    with pytest.raises(AssertionError, match="is not a class in this source"):
        span_by_reading("class Other:\n    pass\n", of=THE_INDEX)
