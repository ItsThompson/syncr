"""Which log every consumer of the habit outcome reader is wired to, read out of the tree.

The rotation cursor and the outstanding debt are derived from the log on every read, by three
components that each acquire it through the same protocol: the week assembler, the habit routes and
the weekly session. A consumer wired to a different reader from its siblings is invisible to every
type check, because the seam is a Protocol, and invisible to every unit test, because each passes
its own double. So the plan can place a rotation habit on one variant while that habit's own screen
names
another, and nothing in either surface says which is wrong.

**The consumers are discovered from the protocol, not listed here.** Any class that annotates a
constructor parameter with the reader's name is one, so a fourth consumer comes under this rule
without an edit, and a class that takes some other reader under the same keyword name does not. That
is the census's own boundary and both edges of it are controlled below.

**The compositions are read from the source rather than imported**, and by the same walk the
placement seam's guard reads with. What the keyword is bound to is the claim; the module that binds
it
also has to have imported that class from the module that defines it, because a local class of the
same name satisfies a name check while reading nothing.

**The prose is crossed against that reading rather than asserted on its own.** The scan refuses the
statements a wired log makes false, over this member's own sources and suites and over the runbook
that carries a row for the read, and it runs only after the wiring has been read: unwire a consumer
and the
wiring case fails first, which is the order that keeps the two from disagreeing. Whitespace is
collapsed before matching, so a sentence that comes back re-wrapped across two lines is still
refused.

What escapes it: a false sentence about the seam that is not one of the statements named below, and
the two shapes ``seam_census`` states it cannot see.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import TYPE_CHECKING

from syncr_api.habits.outcome_log import HabitOutcomeReader
from syncr_api.habits.service import HabitService
from syncr_api.plans import injection
from syncr_api.plans.assembler import WeekAssembler
from syncr_api.plans.habit_log import HabitOutcomeLog
from tests.seam_census import Wiring, seam_wirings
from tests.wire_census import api_modules

if TYPE_CHECKING:
    from collections.abc import Iterable

PRODUCTION_READER = HabitOutcomeLog.__name__
READER_MODULE = HabitOutcomeLog.__module__

# `packages/syncr-api/tests/test_outcome_seam_wiring.py` -> `packages/syncr-api`. Taken from THIS
# FILE rather than from the imported package, so the precondition below crosses the tree this
# checkout holds against the tree the interpreter resolved: in a workspace whose editable installs
# point at another checkout those are two different questions.
MEMBER = Path(__file__).resolve().parents[1]
SOURCE = MEMBER / "src" / "syncr_api"
REPOSITORY = MEMBER.parents[1]
WIRING = "plans/injection.py"

# The runbook that carries a row for this read. An operator reads it under pressure and a row that
# says the read costs nothing is why it is scanned beside the sources.
RUNBOOK = REPOSITORY / "docs" / "runbooks" / "assembly-slow.md"

# The two consumers this seam is named for: the log the habit endpoint reads and the log the
# assembly reads. Named so the census cannot quietly stop finding one of them and still report a
# clean sweep of whatever it did find.
THE_SEAMS_TWO_SIDES = (WeekAssembler, HabitService)

# The statements a wired log makes false. Each existed in this repository while the assembler read
# an empty log, and each is a claim about what the seam answers or about what bringing it online
# costs.
DENIALS_OF_THE_WIRING = (
    "One seam is wired to a reader that answers with nothing",
    "Whoever brings it online changes one line here",
    "One of the eighteen is a stub today",
    "comes through a reader whose production implementation answers with nothing",
    "bringing a reader online changes one line of wiring",
    "the assembler's own outcome seam is still wired to the empty log",
    "Row 13 issues no statement in this deployment",
)

# This module holds those statements as data, so it is the one file the scan may not read. Stated as
# a path rather than a name, and asserted to be a file the scan would otherwise have covered.
THE_SCANS_OWN_FILE = Path(__file__).resolve()


def consumers_of(protocol: type) -> dict[type, str]:
    """Every class of this package that takes ``protocol``, and the keyword it takes it by.

    Read from the constructor's own annotations, which are strings in this package: a Protocol
    parameter is imported under ``TYPE_CHECKING``, so the name is all there is at runtime and it is
    exactly what identifies a consumer. Split into words rather than compared whole, so a consumer
    that takes the reader as one arm of a union is found rather than dropped.
    """
    found: dict[type, str] = {}
    for module in api_modules():
        for value in vars(module).values():
            if not isinstance(value, type) or not value.__module__.startswith("syncr_api."):
                continue
            keyword = _parameter_annotated(value, protocol.__name__)
            if keyword is not None:
                found[value] = keyword
    return found


def _parameter_annotated(cls: type, annotation: str) -> str | None:
    """The constructor keyword this class takes ``annotation`` by, if it takes one at all."""
    try:
        parameters = inspect.signature(cls).parameters
    except (TypeError, ValueError):
        return None
    return next(
        (
            name
            for name, parameter in parameters.items()
            if annotation in re.split(r"\W+", str(parameter.annotation))
        ),
        None,
    )


def log_wirings(source_root: Path, consumers: dict[type, str]) -> dict[type, list[Wiring]]:
    """Every composition of every consumer under ``source_root``, with the log it binds.

    Returns data rather than asserting, so the mapping, its controls and the prose crossing all
    drive one walk.
    """
    return {
        consumer: seam_wirings(source_root, composed=consumer, keyword=keyword)
        for consumer, keyword in consumers.items()
    }


def one_line(text: str) -> str:
    """The text with every run of whitespace collapsed, which is how a wrapped sentence reads."""
    return re.sub(r"\s+", " ", text)


def sources_suites_and_the_runbook() -> tuple[Path, ...]:
    """Every file that describes this seam: both trees of this member, and the runbook.

    Both trees, because the sentences that go stale are written on the production path and in the
    suites that drive it, and a rule stated over one of them would leave the other free. The runbook
    because an operator pastes it under pressure and a row that says a read is free stops them
    looking at it.
    """
    found = (
        *sorted((MEMBER / "src").rglob("*.py")),
        *sorted((MEMBER / "tests").rglob("*.py")),
        RUNBOOK,
    )
    assert RUNBOOK.is_file(), f"{RUNBOOK} does not exist, so the scan passed over it"
    return found


def denying_the_wiring(files: Iterable[Path]) -> dict[Path, list[str]]:
    """Which files state one of the denials, and which ones each states."""
    found: dict[Path, list[str]] = {}
    for path in files:
        source = one_line(path.read_text(encoding="utf-8"))
        stated = [one for one in denials() if one in source]
        if stated:
            found[path] = stated
    return found


def denials() -> tuple[str, ...]:
    """The statements a wired log makes false, with their number asserted.

    A rule driven by a hand-written tuple is only as wide as the tuple, and its control iterates the
    same tuple, so dropping an entry narrows the rule and its control together and nothing reddens.
    """
    assert len(DENIALS_OF_THE_WIRING) == 7, "a denial was dropped from the scan"
    return DENIALS_OF_THE_WIRING


def test_every_consumer_of_the_log_is_composed_with_the_reader_that_reads_it() -> None:
    """The mapping, as an exact reading, so a second composition is a diff a reviewer reads.

    The import is asserted beside the name because the name alone is satisfied by a class defined in
    the composing module, and that is what a stub wired back in would look like.
    """
    consumers = consumers_of(HabitOutcomeReader)

    wired = log_wirings(SOURCE, consumers)

    assert consumers, "no class takes the outcome reader, so this asserted nothing"
    silent = sorted(one.__name__ for one, found in wired.items() if not found)
    assert silent == [], f"{silent} take the log and are composed nowhere in this package"
    for consumer, found in wired.items():
        assert [one.reader for one in found] == [PRODUCTION_READER] * len(found), (
            f"{consumer.__name__} is composed with {[one.reader for one in found]}"
        )
        assert [one.imported_from for one in found] == [READER_MODULE] * len(found), (
            f"{consumer.__name__} reaches the reader from {[one.imported_from for one in found]}"
        )


def test_the_two_sides_of_the_seam_are_both_in_the_census() -> None:
    """The log the habit endpoint reads and the log the assembly reads, named.

    Keyed to the two consumers rather than to the census's own parts: a discovery that quietly
    stopped finding either would otherwise report a clean sweep of whatever it still found, and the
    disagreement this seam exists over is exactly between these two.
    """
    consumers = consumers_of(HabitOutcomeReader)

    missing = [one.__name__ for one in THE_SEAMS_TWO_SIDES if one not in consumers]

    assert missing == [], f"{missing} read the outcome log and the census does not see them"


def test_the_census_reads_a_consumer_and_ignores_another_reader() -> None:
    """Its control, on both edges, over classes built to sit either side of the boundary."""

    class TakesTheLog:
        def __init__(self, *, outcomes: HabitOutcomeReader) -> None:
            self._outcomes = outcomes

    class TakesTheLogOrNothing:
        def __init__(self, *, outcomes: HabitOutcomeReader | None = None) -> None:
            self._outcomes = outcomes

    class TakesAnotherReader:
        def __init__(self, *, outcomes: HabitOutcomeLog) -> None:
            self._outcomes = outcomes

    assert _parameter_annotated(TakesTheLog, HabitOutcomeReader.__name__) == "outcomes"
    assert _parameter_annotated(TakesTheLogOrNothing, HabitOutcomeReader.__name__) == "outcomes"
    assert _parameter_annotated(TakesAnotherReader, HabitOutcomeReader.__name__) is None


def test_the_walk_reports_a_log_seam_wired_to_something_else(tmp_path: Path) -> None:
    """The control on the reading: it names what the keyword is bound to, not what it expects.

    Three spellings of the composition, because a reading that saw only the bare name would report
    one wiring out of three and the mapping above would still pass. Stated for THIS keyword rather
    than borrowed from the placement seam's controls, because the walk takes the keyword as an
    argument and a control keyed to the other seam's would leave this one unread.
    """
    assembler, module = WeekAssembler.__name__, WeekAssembler.__module__
    (tmp_path / "wiring.py").write_text(
        f"from elsewhere import NoLog\n"
        f"def build() -> object:\n"
        f"    return {assembler}(settings=None, outcomes=NoLog())\n",
        encoding="utf-8",
    )
    (tmp_path / "local_stub.py").write_text(
        f"class NoLog:\n    pass\n\n\n"
        f"def build() -> object:\n    return {assembler}(outcomes=NoLog())\n",
        encoding="utf-8",
    )
    (tmp_path / "qualified.py").write_text(
        f"from elsewhere import NoLog\n"
        f"import {module} as composer\n"
        f"def build() -> object:\n    return composer.{assembler}(outcomes=NoLog())\n",
        encoding="utf-8",
    )
    (tmp_path / "aliased.py").write_text(
        f"from elsewhere import NoLog\n"
        f"from {module} import {assembler} as Composer\n"
        f"def build() -> object:\n    return Composer(outcomes=NoLog())\n",
        encoding="utf-8",
    )

    found = seam_wirings(tmp_path, composed=WeekAssembler, keyword="outcomes")

    assert found == [
        Wiring("aliased.py", "NoLog", "elsewhere"),
        Wiring("local_stub.py", "NoLog", None),
        Wiring("qualified.py", "NoLog", "elsewhere"),
        Wiring("wiring.py", "NoLog", "elsewhere"),
    ]


def test_a_tree_that_only_names_the_log_reports_no_wiring(tmp_path: Path) -> None:
    """The other edge of that reading, over what this module and the suites around it hold.

    An import, an attribute read, the name in a string, a construction that is nobody's seam, and a
    consumer's keyword on a call that composes something else. If any of them counted, the mapping
    would be certifying a composition nobody wrote.
    """
    (tmp_path / "mentions.py").write_text(
        f"from {READER_MODULE} import {PRODUCTION_READER}\n"
        f"doc = {PRODUCTION_READER}.__doc__\n"
        f'named = "outcomes={PRODUCTION_READER}()"\n'
        f"log = {PRODUCTION_READER}(1, 2)\n"
        f"other = SomethingElse(outcomes={PRODUCTION_READER}())\n",
        encoding="utf-8",
    )

    assert seam_wirings(tmp_path, composed=WeekAssembler, keyword="outcomes") == []


def test_the_tree_walked_is_the_one_this_checkout_holds() -> None:
    """The precondition, and its two sides are resolved from different places.

    ``injection`` comes from the imported package and ``MEMBER`` from this file's own path, so a run
    whose interpreter answers with another checkout's ``syncr_api`` fails here instead of certifying
    that checkout's wiring against this checkout's statements.
    """
    assert Path(injection.__file__).resolve() == (SOURCE / WIRING).resolve()
    assert PRODUCTION_READER in (SOURCE / WIRING).read_text(encoding="utf-8")


def test_nothing_in_this_member_or_the_runbook_denies_the_wiring() -> None:
    """The prose crossing, in the order that keeps it honest: read the wiring, then refuse a denial.

    A statement that the assembler's log answers with nothing is false while every composition binds
    the real reader, and a false statement about this seam is what let the runbook tell an operator
    that a read which now returns the tenant's whole habit history costs nothing.
    """
    wired = log_wirings(SOURCE, consumers_of(HabitOutcomeReader))
    assert {one.reader for found in wired.values() for one in found} == {PRODUCTION_READER}

    scanned = [path for path in sources_suites_and_the_runbook() if path != THE_SCANS_OWN_FILE]
    denying = denying_the_wiring(scanned)

    assert len(scanned) == len(sources_suites_and_the_runbook()) - 1, (
        "the scan read its own statements"
    )
    assert denying == {}, f"these deny a log that is wired: { {str(one) for one in denying} }"


def test_the_scan_finds_every_denial_it_names(tmp_path: Path) -> None:
    """The control on the crossing, with each denial wrapped across two lines.

    A scan blind to the sentences it lists refuses nothing, and a scan that read them line by line
    would be blind to every one a formatter had re-wrapped, which is how each of these was written.
    """
    written = {}
    for index, denial in enumerate(denials()):
        path = tmp_path / f"stated_{index}.py"
        head, _, tail = denial.partition(" ")
        path.write_text(f'"""A docstring that says {head}\n{tail} today."""\n', encoding="utf-8")
        written[path] = [denial]
    (tmp_path / "silent.py").write_text('"""Says nothing about the seam."""\n', encoding="utf-8")

    assert denying_the_wiring(sorted(tmp_path.rglob("*.py"))) == written


def test_the_scans_own_file_is_one_it_would_otherwise_have_read() -> None:
    """The self-exclusion's other edge: an exemption for a file outside the set exempts nothing."""
    assert THE_SCANS_OWN_FILE in sources_suites_and_the_runbook()
    assert denying_the_wiring([THE_SCANS_OWN_FILE]) == {THE_SCANS_OWN_FILE: list(denials())}
