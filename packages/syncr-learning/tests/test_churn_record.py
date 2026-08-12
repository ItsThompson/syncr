"""The churn corpus's reading, held against the tree the record describes.

``rearrangements.py``'s docstring is where this corpus states which revision pairs are in it and why
the narrower reading, one that keeps only the pairs the user assented to, was declined. Prose rots,
so each clause that can be crossed against the tree is crossed here rather than trusted: the pair
count, the projection's blindness to assent, the gate's denominator, the direction of the narrow
reading's error, and the state that would reopen the question.

The record is read off the module object and the file off ``__file__``, so a reading cannot be aimed
at a file the record does not live in.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

import syncr_api
import syncr_solver
from syncr_api.plans.models import PlanRevision
from syncr_domain.plan import PlanDocument
from syncr_learning import rearrangements
from syncr_learning.config import CHURN_TOLERANCE, THRESHOLD_CHURN_TOLERANCE
from syncr_learning.facts import StoredRevision
from syncr_learning.fitters import fit_churn_tolerance
from syncr_learning.gates import gated
from syncr_learning.observations import ChurnObservation
from syncr_learning.storage import spelling
from syncr_solver.inputs import ChurnBaseline
from tests.builders import WEEK, ZONE, at, planned, revision, span

ASSENT_COLUMNS = ("status", "approved_at")
"""The two columns the narrower reading would have to read. Named once, crossed three ways."""


def _record() -> str:
    """The docstring as the module object carries it, on one line.

    Collapsed, because the prose is wrapped at the line length and a clause that spans a wrap is
    still the clause: keying on the newlines would redden the guard on a reflow.
    """
    assert rearrangements.__doc__ is not None
    return " ".join(rearrangements.__doc__.split())


def _source() -> str:
    """The whole file, from the module's own path, so the prose guards read what shipped."""
    assert rearrangements.__file__ is not None
    return Path(rearrangements.__file__).read_text(encoding="utf-8")


def _history(revisions: int) -> list[StoredRevision]:
    """One week whose every consecutive pair moved its one block somewhere else."""
    return [
        revision(blocks=[planned(interval=span(hour=hour))], created_at=at(hour=hour))
        for hour in range(revisions)
    ]


def _observations(revisions: list[StoredRevision]) -> list[ChurnObservation]:
    return list(rearrangements.churn_observations(revisions, []))


class TestTheRecordStatesTheDeclinedAlternative:
    @pytest.mark.parametrize(
        "clause",
        [
            pytest.param("considered and declined", id="the-alternative-was-weighed"),
            pytest.param(
                "the narrow reading fits HIGHER", id="the-direction-where-the-gap-is-wide"
            ),
            pytest.param(
                "Where the two populations are alike it fits LOWER",
                id="the-direction-where-there-is-no-gap",
            ),
            pytest.param(
                "halves the corpus, which shrinks the figure harder toward the prior",
                id="the-mechanism-that-turns-the-sign",
            ),
            pytest.param(
                "conditional on a gap nothing here measures", id="the-direction-is-conditional"
            ),
            pytest.param("the product prefers the low one", id="which-error-is-preferred"),
            pytest.param("THRESHOLD_CHURN_TOLERANCE = 20", id="the-gate-figure"),
            pytest.param(
                "rate revisions are produced rather than the rate a human approves",
                id="what-the-gate-figure-is-denominated-in",
            ),
            pytest.param("What reopens this", id="what-would-reopen-the-question"),
        ],
    )
    def test_the_record_still_states(self, clause: str) -> None:
        assert clause in _record()

    @pytest.mark.parametrize(
        ("pattern", "shape"),
        [
            pytest.param(r"ticket \d+", "ticket 0", id="a-ticket-number"),
            pytest.param(r"\bSP1-[A-Z]+-\d+\b", "SP1-NONE-0", id="an-epic-id"),
            pytest.param(r"\bUS-[A-Z]+-\d+\b", "US-NONE-0", id="a-story-id"),
            pytest.param(r"\bsection \d+", "section 0", id="a-spec-section"),
            pytest.param(r"§\s*\d+", "§0", id="a-spec-section-sign"),
            pytest.param(r"\bAC\d+\b", "AC0", id="an-acceptance-criterion"),
            pytest.param(r"\breview \d+", "review 0", id="a-review-round"),
            pytest.param(
                r"\b(?:milestone|slice|wave) \d+", "milestone 0", id="delivery-plan-language"
            ),
        ],
    )
    def test_the_record_names_no_planning_artifact(self, pattern: str, shape: str) -> None:
        # `shape` is the control: a pattern that matches nothing anywhere would pass the file
        # assertion while looking like a guard, so each one is shown to match its own shape first.
        assert re.search(pattern, shape, re.IGNORECASE) is not None
        assert re.search(pattern, _source(), re.IGNORECASE) is None


class TestEveryConsecutivePairIsInTheCorpus:
    def test_a_week_of_five_revisions_yields_four_rearrangements(self) -> None:
        observed = _observations(_history(5))

        assert [one.moves for one in observed] == [1, 1, 1, 1]

    def test_a_week_whose_every_pair_moved_opens_the_gate_at_twenty_one_revisions(self) -> None:
        # The fixture's own property, which is why this is not "the gate counts the pairs the week
        # produced": the two counts coincide only because every pair here moved. The sibling below
        # is the week where they come apart.
        history = _history(THRESHOLD_CHURN_TOLERANCE + 1)

        opened = fit_churn_tolerance(_observations(history))
        closed = fit_churn_tolerance(_observations(history[:-1]))

        assert opened.samples == THRESHOLD_CHURN_TOLERANCE
        assert gated(CHURN_TOLERANCE, opened) is not None
        assert closed.samples == THRESHOLD_CHURN_TOLERANCE - 1
        assert gated(CHURN_TOLERANCE, closed) is None

    def test_a_quiet_revision_is_in_the_corpus_and_not_in_the_gate_s_count(self) -> None:
        # The two counts are not the same count. Every consecutive pair is an observation, and the
        # fit then drops the pairs that moved nothing, so a week holding one repeated arrangement
        # produces one more observation than the gate counts.
        history = _history(THRESHOLD_CHURN_TOLERANCE + 2)
        quiet = list(history)
        quiet[11] = revision(blocks=history[10].blocks, created_at=at(hour=11))

        observed = _observations(quiet)
        fitted = fit_churn_tolerance(observed)

        assert len(observed) == len(quiet) - 1
        assert [one.moves for one in observed].count(0) == 1
        assert fitted.samples == len(observed) - 1
        assert fitted.samples == THRESHOLD_CHURN_TOLERANCE


class TestTheProjectionCannotSeeAssent:
    def test_the_row_this_corpus_reads_is_the_row_that_carries_assent(self) -> None:
        # Which is why the record declines the narrow reading on its bias rather than on its cost.
        assert PlanRevision.__tablename__ == spelling.PLAN_REVISIONS
        assert set(ASSENT_COLUMNS) <= set(PlanRevision.__table__.columns.keys())

    def test_no_name_this_job_restates_is_an_assent_column(self) -> None:
        spelled = _spelled_names()

        assert spelling.DOCUMENT in spelled
        assert spelled.isdisjoint(ASSENT_COLUMNS)

    def test_the_revision_projection_carries_no_assent_field(self) -> None:
        fields = {one.name for one in dataclasses.fields(StoredRevision)}

        assert "created_at" in fields
        assert fields.isdisjoint(ASSENT_COLUMNS)


class TestTheDirectionOfTheNarrowReadingsError:
    """The sign of the difference, across the gap that decides it rather than at one point."""

    @pytest.mark.parametrize(
        ("pairs", "overridden", "wider", "narrow", "narrow_fits_higher"),
        [
            pytest.param(20, 0, 6.333333, 5.5, False, id="alike-populations-fit-lower"),
            pytest.param(20, 1, 6.0, 5.5, False, id="a-gap-of-one-fits-lower"),
            pytest.param(20, 2, 5.666667, 5.5, False, id="the-last-gap-that-fits-lower"),
            pytest.param(20, 3, 5.333333, 5.5, True, id="the-first-gap-that-fits-higher"),
            pytest.param(20, 7, 4.0, 5.5, True, id="the-gap-the-record-argues-from"),
            pytest.param(60, 1, 6.857143, 6.75, False, id="past-the-gate-and-still-lower"),
            pytest.param(60, 2, 6.428571, 6.75, True, id="past-the-gate-and-higher"),
        ],
    )
    def test_the_sign_turns_on_the_size_of_the_gap(
        self,
        pairs: int,
        overridden: int,
        wider: float,
        narrow: float,
        narrow_fits_higher: bool,
    ) -> None:
        # Half the rearrangements were let stand and half had `overridden` of their eight moves
        # pinned back. The narrow reading keeps the first half, which drops the objections AND
        # halves the evidence: the mean of what was absorbed rises, and the shrinkage toward the
        # prior rises with it. Which effect wins is what these rows measure, and it changes sign.
        assented = [ChurnObservation(moves=8, overridden=0) for _ in range(pairs // 2)]
        objected = [ChurnObservation(moves=8, overridden=overridden) for _ in range(pairs // 2)]

        wider_fit = fit_churn_tolerance([*assented, *objected])
        narrow_fit = fit_churn_tolerance(assented)

        assert wider_fit.value is not None
        assert narrow_fit.value is not None
        assert wider_fit.value == pytest.approx(wider, abs=1e-6)
        assert narrow_fit.value == pytest.approx(narrow, abs=1e-6)
        assert (narrow_fit.value > wider_fit.value) is narrow_fits_higher

    def test_the_sixty_pair_rows_compare_two_readings_the_gate_both_admits(self) -> None:
        # Without this the sign at sixty pairs would compare a figure that is applied against one
        # that is not, which is two questions at once.
        assented = [ChurnObservation(moves=8, overridden=0) for _ in range(30)]
        objected = [ChurnObservation(moves=8, overridden=2) for _ in range(30)]

        assert gated(CHURN_TOLERANCE, fit_churn_tolerance([*assented, *objected])) is not None
        assert gated(CHURN_TOLERANCE, fit_churn_tolerance(assented)) is not None

    def test_at_twenty_pairs_the_narrowing_also_takes_the_corpus_below_the_gate(self) -> None:
        assented = [ChurnObservation(moves=8, overridden=0) for _ in range(10)]
        objected = [ChurnObservation(moves=8, overridden=7) for _ in range(10)]

        assert gated(CHURN_TOLERANCE, fit_churn_tolerance([*assented, *objected])) is not None
        assert gated(CHURN_TOLERANCE, fit_churn_tolerance(assented)) is None


class TestWhatWouldReopenTheQuestion:
    def test_a_baseline_naming_an_approved_revision_carries_no_plan(self) -> None:
        baseline = ChurnBaseline.approved(UUID(int=1), datetime(2026, 2, 9, tzinfo=UTC))

        assert baseline.is_measured is False
        assert baseline.reason == ChurnBaseline.APPROVED_UNREADABLE

    def test_the_same_baseline_handed_a_plan_reports_one(self) -> None:
        # The control. Without it the assertion above could be passing on a property that answers
        # the same way whatever the baseline holds.
        baseline = ChurnBaseline.approved(
            UUID(int=1), datetime(2026, 2, 9, tzinfo=UTC), _an_empty_week()
        )

        assert baseline.is_measured is True
        assert baseline.reason == ChurnBaseline.APPROVED_REVISION

    def test_a_shipped_caller_hands_the_baseline_a_plan(self) -> None:
        # The record's reopening condition, crossed against the tree rather than trusted. Three
        # arguments at the one shipped producer: the revision, the instant of assent, and the plan
        # that revision stored, which is what the term reads.
        producers = _approved_baseline_producers()

        assert producers, "no shipped module builds an approved churn baseline"
        assert set(producers.values()) == {3}


def _spelled_names() -> set[str]:
    """Every table, column and document key this job's I/O restates."""
    found: set[str] = set()
    for name, value in vars(spelling).items():
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, tuple):
            found.update(one for one in value if isinstance(one, str))
    return found


def _an_empty_week() -> PlanDocument:
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), ZONE),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
    )


def _approved_baseline_producers() -> dict[str, int]:
    """Each shipped call that builds an approved baseline, by site, and how many arguments it hands.

    The two trees walked are the solver's, which declares the value, and the api's, which builds it.
    A producer written outside those two is not seen here, and neither is one reached through an
    alias of the class name: an aliased producer empties this walk, which the caller's non-empty
    assertion then catches.
    """
    found: dict[str, int] = {}
    for root in (Path(syncr_solver.__file__).parent, Path(syncr_api.__file__).parent):
        reached = 0
        for module in sorted(root.rglob("*.py")):
            reached += 1
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _builds_an_approved_baseline(node.func):
                    site = f"{root.name}/{module.relative_to(root)}:{node.lineno}"
                    found[site] = len(node.args) + len(node.keywords)
        assert reached, f"the walk read no module under {root}, so it can find no producer there"
    return found


def _builds_an_approved_baseline(func: ast.expr) -> bool:
    if not isinstance(func, ast.Attribute) or func.attr != "approved":
        return False
    named = func.value
    if isinstance(named, ast.Name):
        return named.id == ChurnBaseline.__name__
    return isinstance(named, ast.Attribute) and named.attr == ChurnBaseline.__name__
