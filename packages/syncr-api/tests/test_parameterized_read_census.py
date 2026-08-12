"""The census over the parameterized reads: every one is driven or exempt, and neither set is quiet.

``tests/boundaries.py`` splits this api's GET routes by whether they carry a path parameter, because
driving a parameterized read needs a value invented for the parameter. The two halves are then
driven separately. The parameterless half is driven by the never-writes guard in
``test_horizon_maintainer.py``, which drives all of them but one endless read it excludes by name
and asserts the existence of. The parameterized half was driven by the week guards in
``test_week_routes_integration.py``, which took whatever matched the week prefix.

A filter answers what it matches and cannot report what it leaves out. So every parameterized read
outside the week prefix was inherited undriven by any guard stated over the route table, and nothing
in the suite said so. A named exclusion that has to exist is the shape the other half already had;
this is that shape for this one.

This module equates the two accounted-for sets with what the application declares, so a read named
by neither fails by name. Five ways that equality goes quiet are asserted beside it: an exemption
for a route that does not exist, an exemption for a route a driver reaches after all, a reason
copied from a route addressed by another value, a contribution that derives nothing, and a
contribution that derives a read the application does not serve.

The registry holds every derivation of driven reads the suite has, and holding one fewer is the one
failure this module cannot see: the reads that derivation drives become declared gaps, and each
field above stays empty. Both contributions were written before the census, and the second was
found by sweeping the suite for readers of the route table rather than for callers of one function.

Every rule here runs against the real application and against a synthetic input built to fail it.
The census returns data rather than asserting, which is what makes both readings the same reading.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import APIRouter

from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.settings import API_PREFIX
from tests.boundaries import (
    DRIVEN_READ_CONTRIBUTIONS,
    EXEMPT_PARAMETERIZED_READS,
    census_of_reads,
    path_parameters,
    read_paths,
)
from tests.source_census import imported_as, named, tracked_python_sources

if TYPE_CHECKING:
    from fastapi import FastAPI

    from syncr_api.core.settings import ServiceSettings
    from tests.boundaries import DrivenReads

# The parameter a synthetic read declares. One name, so the handler below can declare it: FastAPI
# resolves a path parameter against the handler's own signature.
SYNTHETIC_PARAMETER = "synthetic_id"
SYNTHETIC_SEGMENT = "synthetic"

# A read no contribution derives and no exemption names, which is the arrival this census exists to
# fail on, and one under a prefix a contribution already covers, which is the same arrival being
# driven. Both edges of one reading.
READ_UNDER_NO_CONTRIBUTION = f"{API_PREFIX}/{SYNTHETIC_SEGMENT}/{{{SYNTHETIC_PARAMETER}}}"
READ_UNDER_THE_WEEK_PREFIX = f"{WEEKS_PREFIX}/{{{SYNTHETIC_PARAMETER}}}/{SYNTHETIC_SEGMENT}"

# How a source reaches a published contribution, and whether the reading below counts it as one.
#
# THE MODULE-QUALIFIED FORM IS THE ONE THIS READING CANNOT MATCH, and it is stated here so the
# blind spot is published rather than discovered. A suite reaching a contribution that way leaves
# the reading finding no reader at all, which is red rather than quiet: the direction a blind spot
# has to fail in.
CONSUMPTION_SPELLINGS = (
    ("imported and called", "from tests.boundaries import {name}\nfound = {name}(app)\n", True),
    (
        "imported under an alias and called",
        "from tests.boundaries import {name} as _reads\nfound = _reads(app)\n",
        True,
    ),
    (
        "imported and called inside a function",
        "from tests.boundaries import {name}\n\ndef driver():\n    return {name}(app)\n",
        True,
    ),
    (
        "imported and never called",
        "from tests.boundaries import {name}\nfound = {name}\n",
        False,
    ),
    (
        "a local function of the same name, called",
        "def {name}(app):\n    return []\n\nfound = {name}(app)\n",
        False,
    ),
    (
        "reached through the module, which this reading cannot see",
        "from tests import boundaries\nfound = boundaries.{name}(app)\n",
        False,
    ),
)


def app_with_a_read(path: str, settings: ServiceSettings) -> FastAPI:
    """The real application, plus one parameterized read contributed by an included router.

    An include rather than a route registered on the app, because that is how this application
    declares every one of its own: a census blind to an expanded include would pass this control
    while covering nothing that matters.
    """
    assert path_parameters(path) == {SYNTHETIC_PARAMETER}, "the handler below declares that one"
    router = APIRouter()

    @router.get(path)
    async def _read(synthetic_id: str) -> dict[str, str]:  # pragma: no cover - never requested
        return {SYNTHETIC_PARAMETER: synthetic_id}

    app = create_app(settings)
    app.include_router(router)
    return app


def reads_a_contribution(tree: ast.Module, contribution: DrivenReads) -> bool:
    """Whether this source imports one published contribution from its own module and calls it.

    Both halves are exact names on syntax nodes rather than text. A call is a call node whose
    trailing name is one this source bound by importing the contribution, so a source defining a
    function of that name has bound nothing from the registry and is not a reader of it.
    """
    local = imported_as(tree, module=contribution.__module__, names=(contribution.__name__,))
    return any(isinstance(node, ast.Call) and named(node.func) in local for node in ast.walk(tree))


def suite_modules() -> tuple[Path, ...]:
    """Every module of this suite except this census and the one publishing the contributions.

    The publisher is excluded because defining a contribution is not driving one, and this module is
    excluded because a census counting its own reading would certify every contribution it reads.
    Taken from the index, so a module staged and not yet committed is covered.
    """
    here = Path(__file__).resolve()
    publishers = {
        Path(inspect.getfile(contribution)).resolve() for contribution in DRIVEN_READ_CONTRIBUTIONS
    }
    found = tuple(
        path
        for path in tracked_python_sources()
        if path.resolve().parent == here.parent and path.resolve() not in publishers | {here}
    )
    assert found, "no module of this suite was found, so the reading below covers nothing"
    return found


def test_every_parameterized_read_is_driven_or_exempt(settings: ServiceSettings) -> None:
    """The census. A read the application declares that neither set names fails here by name.

    Both sets are read off the registry rather than restated here, so a feature module's new read is
    accounted for by a contribution deriving it or by an exemption saying what a driver would have
    to invent, and by nothing else.
    """
    app = create_app(settings)
    census = census_of_reads(app)

    assert census.driven, "no contribution derived a read, so this equality asserts nothing"
    assert census.driven | census.exempt == set(read_paths(app, parameterized=True)), (
        f"reads no contribution derives and no exemption names: "
        f"{sorted(census.covered_by_neither)}. Exemptions for a read the application does not "
        f"declare: {sorted(census.exempt_but_undeclared)}. Contributions deriving a read the "
        f"application does not declare: {sorted(census.driven_but_undeclared)}"
    )


def test_no_contribution_derives_a_read_the_application_does_not_declare(
    settings: ServiceSettings,
) -> None:
    """So a contribution cannot answer with a path nothing serves.

    Reported as its own field because it is the third way the equality above can move, and the two
    lists that equality names would both be empty: an operator would be handed a red test whose
    message named nothing.
    """
    census = census_of_reads(create_app(settings))

    assert census.driven_but_undeclared == frozenset()


def test_no_exemption_names_a_read_a_contribution_drives(settings: ServiceSettings) -> None:
    """So a gap that has since been closed cannot go on being stated as one.

    The equality above holds either way, because such a read is accounted for twice. What it loses
    is its meaning: the exemption's reason then describes a read something drives.
    """
    census = census_of_reads(create_app(settings))

    assert census.exempt_but_driven == frozenset()


def test_every_exemption_names_the_value_a_driver_would_have_to_invent(
    settings: ServiceSettings,
) -> None:
    """The reason is prose, and this is the part of one a reading can hold to its route.

    Nothing can read a reason for truth. It can be required to name the parameter the route is
    addressed by, in the template's own spelling, which is what a reason copied from another route
    fails to do.
    """
    census = census_of_reads(create_app(settings))

    assert census.exempt_without_naming_its_parameter == frozenset()


def test_every_contribution_derives_at_least_one_read(settings: ServiceSettings) -> None:
    """A contribution matching no route has gone blind, and the equality cannot see the difference.

    It would go on subtracting nothing while the reads it was written for moved into the set nothing
    covers, so the census would report them as a new gap rather than as this one.
    """
    census = census_of_reads(create_app(settings))

    assert census.contributions_deriving_nothing == ()


@pytest.mark.parametrize(
    "contribution", DRIVEN_READ_CONTRIBUTIONS, ids=lambda given: given.__name__
)
def test_every_contribution_is_read_by_a_guard_that_drives_it(contribution: DrivenReads) -> None:
    """The other edge of the registry: a contribution nobody consumes drives nothing.

    Publishing a set of reads covers them only while a guard takes its paths from it. Without this,
    a contribution could be added to silence the census with no request ever made, which is a
    coverage token rather than coverage.
    """
    readers = [
        path.name
        for path in suite_modules()
        if reads_a_contribution(ast.parse(path.read_text(encoding="utf-8")), contribution)
    ]

    assert readers, f"nothing outside {Path(inspect.getfile(contribution)).name} calls it"


def test_a_read_the_application_declares_and_neither_set_names_fails_the_census(
    settings: ServiceSettings,
) -> None:
    """The positive control, on the real application rather than on a bare one.

    A census narrowed to nothing passes every assertion above, because the exemption table was
    written against the same route table the census reads. One route the application declares that
    neither set names is what separates a census that discriminates from one that matches nothing.
    """
    census = census_of_reads(app_with_a_read(READ_UNDER_NO_CONTRIBUTION, settings))

    assert census.covered_by_neither == frozenset({READ_UNDER_NO_CONTRIBUTION})
    assert READ_UNDER_NO_CONTRIBUTION not in census.driven | census.exempt


def test_a_read_arriving_under_a_prefix_a_contribution_covers_is_driven(
    settings: ServiceSettings,
) -> None:
    """The control's other edge, and the reason a contribution is a derivation and not a list.

    A week read a later feature module adds is driven by the guards that consume the week
    contribution, with no edit to the registry and no edit here.
    """
    census = census_of_reads(app_with_a_read(READ_UNDER_THE_WEEK_PREFIX, settings))

    assert READ_UNDER_THE_WEEK_PREFIX in census.driven
    assert census.covered_by_neither == frozenset()


def test_the_census_reports_an_exemption_for_a_read_the_application_does_not_declare(
    settings: ServiceSettings,
) -> None:
    """The other direction of the equality: an exemption that has outlived its route.

    Keyed by ROUTE rather than by prefix, so an exemption for a path this api never declared is
    reported even while every route it does declare is accounted for.
    """
    retired = f"{API_PREFIX}/{SYNTHETIC_SEGMENT}/{{{SYNTHETIC_PARAMETER}}}"

    census = census_of_reads(
        create_app(settings),
        exemptions={**EXEMPT_PARAMETERIZED_READS, retired: f"{{{SYNTHETIC_PARAMETER}}} names one"},
    )

    assert census.exempt_but_undeclared == frozenset({retired})


def test_the_census_reports_an_exemption_for_a_read_that_is_driven_after_all(
    settings: ServiceSettings,
) -> None:
    """Stated over a planted read a contribution derives, so no real exemption has to be wrong."""
    app = app_with_a_read(READ_UNDER_THE_WEEK_PREFIX, settings)
    reason = f"{{{SYNTHETIC_PARAMETER}}} names a record something stored"

    census = census_of_reads(app, exemptions={READ_UNDER_THE_WEEK_PREFIX: reason})

    assert census.exempt_but_driven == frozenset({READ_UNDER_THE_WEEK_PREFIX})


def test_the_census_reports_a_reason_that_names_another_routes_parameter(
    settings: ServiceSettings,
) -> None:
    """A reason describing a route addressed by a different value, which is what it can catch.

    What a token comparison cannot catch is a reason pasted between two routes that take the SAME
    parameter, and eight of the exemptions are such pairs: a resource and its preference or its
    sub-collection. Those are the two cases a reader has to tell apart, and only the first is
    mechanical.
    """
    exempt, *_ = sorted(EXEMPT_PARAMETERIZED_READS)
    borrowed = f"{{{SYNTHETIC_PARAMETER}}} names something addressed by another route"

    census = census_of_reads(create_app(settings), exemptions={exempt: borrowed})

    assert census.exempt_without_naming_its_parameter == frozenset({exempt})


def test_the_census_reports_a_contribution_deriving_a_read_the_application_does_not_declare(
    settings: ServiceSettings,
) -> None:
    def derives_a_read_that_does_not_exist(app: FastAPI) -> list[str]:
        return [*read_paths(app, parameterized=True), READ_UNDER_NO_CONTRIBUTION]

    census = census_of_reads(
        create_app(settings), contributions=(derives_a_read_that_does_not_exist,)
    )

    assert census.driven_but_undeclared == frozenset({READ_UNDER_NO_CONTRIBUTION})


def test_the_census_reports_a_contribution_that_derives_nothing(
    settings: ServiceSettings,
) -> None:
    def derives_nothing(app: FastAPI) -> list[str]:
        return [path for path in read_paths(app, parameterized=True) if path.startswith("/renamed")]

    census = census_of_reads(create_app(settings), contributions=(derives_nothing,))

    assert census.contributions_deriving_nothing == (derives_nothing.__name__,)


@pytest.mark.parametrize(
    "contribution", DRIVEN_READ_CONTRIBUTIONS, ids=lambda given: given.__name__
)
@pytest.mark.parametrize(
    ("spelling", "counts"),
    [(spelling, counts) for _, spelling, counts in CONSUMPTION_SPELLINGS],
    ids=[label for label, _, _ in CONSUMPTION_SPELLINGS],
)
def test_the_consumption_reading_answers_each_spelling_as_published(
    contribution: DrivenReads, spelling: str, counts: bool
) -> None:
    """Both edges of that reading, including the form it cannot see."""
    source = spelling.format(name=contribution.__name__)

    assert reads_a_contribution(ast.parse(source), contribution) is counts
