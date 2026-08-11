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
            pytest.param("fits a HIGHER tolerance", id="the-direction-of-the-error"),
            pytest.param("low is the safer error", id="which-error-is-preferred"),
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

    def test_the_gate_counts_the_pairs_the_week_produced(self) -> None:
        history = _history(THRESHOLD_CHURN_TOLERANCE + 1)

        opened = fit_churn_tolerance(_observations(history))
        closed = fit_churn_tolerance(_observations(history[:-1]))

        assert opened.samples == THRESHOLD_CHURN_TOLERANCE
        assert gated(CHURN_TOLERANCE, opened) is not None
        assert closed.samples == THRESHOLD_CHURN_TOLERANCE - 1
        assert gated(CHURN_TOLERANCE, closed) is None


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
    def test_it_fits_the_higher_tolerance_over_one_history(self) -> None:
        # Ten rearrangements the user let stand and ten they pinned nearly all of back. The narrow
        # reading keeps the first ten, which is where the record's HIGHER comes from: 4.5 absorbed
        # per rearrangement becomes 8, both shrunk toward a prior of 3 at a weight of 10.
        assented = [ChurnObservation(moves=8, overridden=0) for _ in range(10)]
        objected = [ChurnObservation(moves=8, overridden=7) for _ in range(10)]

        wider = fit_churn_tolerance([*assented, *objected])
        narrow = fit_churn_tolerance(assented)

        assert wider.value == pytest.approx(4.0)
        assert narrow.value == pytest.approx(5.5)
        assert narrow.value is not None
        assert wider.value is not None
        assert narrow.value > wider.value

    def test_and_the_same_narrowing_takes_the_corpus_below_the_gate(self) -> None:
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

    def test_no_shipped_caller_hands_the_baseline_a_plan(self) -> None:
        # The record says the churn term charges nothing today. The term reads the baseline's
        # document, and this is what would change first: a third argument at a producer.
        producers = _approved_baseline_producers()

        assert producers, "no shipped module builds an approved churn baseline"
        assert set(producers.values()) == {2}


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
    A producer written outside those two is not seen here.
    """
    found: dict[str, int] = {}
    reached = 0
    for root in (Path(syncr_solver.__file__).parent, Path(syncr_api.__file__).parent):
        for module in sorted(root.rglob("*.py")):
            reached += 1
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _builds_an_approved_baseline(node.func):
                    found[f"{module.name}:{node.lineno}"] = len(node.args) + len(node.keywords)
    assert reached > 1, "the walk read no module, so it can find no producer"
    return found


def _builds_an_approved_baseline(func: ast.expr) -> bool:
    if not isinstance(func, ast.Attribute) or func.attr != "approved":
        return False
    named = func.value
    if isinstance(named, ast.Name):
        return named.id == ChurnBaseline.__name__
    return isinstance(named, ast.Attribute) and named.attr == ChurnBaseline.__name__
