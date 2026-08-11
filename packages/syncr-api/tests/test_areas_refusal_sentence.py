"""The sentence a full ramp is refused with, read rather than driven.

Three claims about that sentence are not claims about the service, so they are stated here rather
than in the service suite: that it says what the service suite cannot see it say, that it offers
nothing the api has no route for, and that one module composes it.

The last one is what keeps two callers from wording the refusal differently. A comparison of
details cannot establish it: a second caller raising a verbatim copy of the sentence answers the
same words, and every assertion that reads the constant passes. What separates the two is where the
words are written, so this reads the source.

**It reads the source as string literals rather than as file text.** A copy breaks its lines where
its own author breaks them, so a clause matched against contiguous file text is invisible in any
copy that wraps elsewhere while composing the same sentence. Joining the literal parts of one
string expression undoes the wrapping, which normalising whitespace cannot: what sits between two
adjacent literals is a quote and sometimes an ``f``, not a space. ``test_areas_log_fields.py`` reads
module source through ``ast`` for the same kind of rule.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from syncr_api.areas.config import AREA_PATH, AREAS_PREFIX, PROJECT_RESOURCE
from syncr_api.areas.rules import FULL_RAMP_REFUSAL
from syncr_domain.pigments import PIGMENT_COUNT
from tests.boundaries import api_routes, route_identity

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

# The collection and one member of it. Built from the route module's own constants, and narrow on
# purpose: a subresource under an Area's path is removable without the Area being.
THE_AREA_PATHS = (AREAS_PREFIX, f"{AREAS_PREFIX}{AREA_PATH}")

# One clause of the refusal, crossed against the sentence itself below so rewording it moves this
# reading rather than leaving it looking for words nobody writes any more.
A_CLAUSE_OF_THE_REFUSAL = "so there is no step left to deal and this one was not stored"

# Stems, so a tense or a plural cannot slip past. Four verbs rather than one, because a sentence
# offering to archive or to retire an Area promises exactly as much as one offering to remove it.
REMOVAL_WORDS = ("remov", "delet", "archiv", "retir")


def literal_runs(source: str) -> list[str]:
    """Every run of literal text a string expression in this source composes.

    The parts of one expression are joined, so an implicit concatenation and an f-string read as
    the sentence they build rather than as the lines they were typed on. An interpolation
    contributes nothing to the run, so a run reads across one.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.JoinedStr):
            found.append(
                "".join(
                    part.value
                    for part in node.values
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                )
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append(node.value)
    return found


def test_the_refusal_names_the_cap_and_what_a_caller_can_still_do() -> None:
    # Everything a caller needs to act on: how many steps there are, that the declaration did
    # not land, and the three things this refusal does not stop them doing.
    assert str(PIGMENT_COUNT) in FULL_RAMP_REFUSAL
    assert "Nothing was changed" in FULL_RAMP_REFUSAL
    assert "still reads as it did" in FULL_RAMP_REFUSAL
    assert "renamed" in FULL_RAMP_REFUSAL
    assert f"fits inside one as a {PROJECT_RESOURCE}" in FULL_RAMP_REFUSAL


def test_the_refusal_offers_no_removal_while_no_route_removes_an_area(app: FastAPI) -> None:
    # An Area is permanent: nothing removes one, so a refusal that suggested removing one would
    # send a caller looking for a control that does not exist. Read off the route table rather
    # than remembered, so the day a removal route lands this says the sentence may offer it.
    removals = sorted(
        identity
        for route in api_routes(app)
        for identity in route_identity(route)
        if identity[0] == "DELETE" and identity[1] in THE_AREA_PATHS
    )
    offered = [word for word in REMOVAL_WORDS if word in FULL_RAMP_REFUSAL.lower()]

    assert bool(offered) == bool(removals), (
        f"the refusal names removal in {offered} and the Area routes answer {removals}. The "
        "sentence may offer removal exactly when a route performs one."
    )


def test_one_module_composes_the_refusal(source_root: Path) -> None:
    assert A_CLAUSE_OF_THE_REFUSAL in FULL_RAMP_REFUSAL, (
        "the refusal was reworded, so this reading is looking for a clause it no longer "
        "carries. Point it at the new one."
    )

    holding = sorted(
        str(module.relative_to(source_root))
        for module in source_root.rglob("*.py")
        if any(
            A_CLAUSE_OF_THE_REFUSAL in run
            for run in literal_runs(module.read_text(encoding="utf-8"))
        )
    )

    assert holding == ["areas/rules.py"], (
        f"{holding} compose the refusal. One module does, so a second caller cannot word it "
        "differently."
    )


@pytest.mark.parametrize(
    ("source", "composes_it"),
    [
        ('THE_WORDS = "a run holding the clause and more"', True),
        ('THE_WORDS = (\n    "a run holding the "\n    "clause and more"\n)', True),
        ('THE_WORDS = (\n    f"a run holding{PAD} the "\n    "clause and more"\n)', True),
        ('THE_WORDS = f"a run holding the clause {AND} more"', False),
        ('THE_WORDS = "a run holding another sentence entirely"', False),
    ],
    ids=[
        "one literal",
        "wrapped between the words",
        "wrapped, with an interpolation beside the words",
        "an interpolation inside the words, which this reading cannot see",
        "no such clause",
    ],
)
def test_the_reading_finds_a_clause_however_its_source_is_wrapped(
    source: str, composes_it: bool
) -> None:
    # The control on the reading above, and the statement of its one hole. A copy that wraps
    # anywhere composes the clause and is found; a copy that interpolates inside the clause
    # itself is not, and no test of this suite would see it.
    found = any("clause and more" in run for run in literal_runs(source))

    assert found is composes_it
