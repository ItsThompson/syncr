"""Which revisions the corpus trains on, and the column it cannot see.

The plan of record is the latest revision of each week. Nothing narrows that set, so a week whose
latest revision was MATERIALIZED is in the corpus beside the weeks a user approved, and a
materialized week's arrangement was chosen by nobody: it is what the declarations determine, with
every Area slot left unfilled.

The inclusion is driven rather than argued. A real ``materialize`` output goes through the api's own
stored form and this job's own projection, and ``extract`` is asked what it made of it, so the
answer is a count of observations rather than a reading of the selection rule.

The other half is why the rule is what it is: what produced a revision is a column on the row and is
not in the projection this job reads, so this function could not narrow the set even if the product
decided it should. Both directions are asserted, because the api dropping the column and the
projection gaining it would each make the statement in ``features`` false.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from syncr_api.plans.models import PlanRevision
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.identity import block_id
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_learning import features
from syncr_learning.facts import LoggedOutcome, StoredRevision
from syncr_learning.features import extract, plans_of_record
from syncr_learning.storage import documents
from syncr_solver import MaterializeCause, materialize
from syncr_solver.inputs import AreaBudget, EntryBinding, MaterializedEntry, SolveInputs
from tests.builders import AREA, MONDAY, OTHER_AREA, WEEK, ZONE, at, corpus, outcome, planned
from tests.builders import revision as stored_revision

if TYPE_CHECKING:
    from syncr_domain.plan import PlanDocument
    from syncr_learning.facts import PlannedBlock, TenantCorpus

PRODUCED_A_REVISION = ("reason", "status", "objective_breakdown")
"""The columns that say what produced a revision. Named once, crossed in both directions."""

FIRST_ENTRY = UUID("44444444-4444-4444-8444-444444444444")
SECOND_ENTRY = UUID("66666666-6666-4666-8666-666666666666")
SLOT_ENTRY = UUID("77777777-7777-4777-8777-777777777777")
ROUTINE = UUID("55555555-5555-4555-8555-555555555555")


def _entry(*, entry_id: UUID, hour: int, kind: TemplateEntryKind) -> MaterializedEntry:
    """One template entry of Monday, resolved for the date the week's first day falls on."""
    start = MONDAY + timedelta(hours=hour)
    named = kind is TemplateEntryKind.CONCRETE
    return MaterializedEntry(
        entry_id=entry_id,
        occurrence_key=MONDAY.date().isoformat(),
        kind=kind,
        interval=Interval(start, start + timedelta(minutes=60)),
        flex_band_minutes=0,
        area_id=AREA,
        day_type_name="Uni day",
        title="Deep work" if named else None,
        binding=EntryBinding(target=BindingTarget.ROUTINE, entity_id=ROUTINE) if named else None,
    )


def _inputs(*, entries: tuple[MaterializedEntry, ...]) -> SolveInputs:
    return SolveInputs(
        iso_week=WEEK,
        span=Interval(MONDAY, MONDAY + timedelta(days=7)),
        now=MONDAY,
        zone_by_date=dict.fromkeys(WEEK.dates(), ZONE),
        input_version=1,
        template_entries=entries,
        areas=(
            AreaBudget(
                area_id=AREA,
                name="Career",
                floor_minutes=60,
                floor_reservation_minutes=60,
                target_minutes=600,
                placed_minutes=0,
            ),
        ),
    )


def _two_concrete_entries() -> tuple[MaterializedEntry, ...]:
    """Two entries an hour apart, which is one adjacency the switch fitter can read."""
    return (
        _entry(entry_id=FIRST_ENTRY, hour=9, kind=TemplateEntryKind.CONCRETE),
        _entry(entry_id=SECOND_ENTRY, hour=10, kind=TemplateEntryKind.CONCRETE),
    )


def _document(entries: tuple[MaterializedEntry, ...]) -> PlanDocument:
    return materialize(_inputs(entries=entries), cause=MaterializeCause.CHECKPOINT)


def _materialized(*, entries: tuple[MaterializedEntry, ...], hour: int = 6) -> StoredRevision:
    """A revision of :data:`WEEK` holding what ``materialize`` derives for ``entries``.

    Written through the api's own stored form and read back through this job's own projection, so
    the blocks are the ones a nightly run would actually load rather than ones this file composed.
    """
    stored = stored_document(_document(entries))
    return StoredRevision(
        iso_week=WEEK,
        created_at=at(hour=hour),
        zone_by_date=documents.zone_by_date(stored),
        blocks=documents.planned_blocks(stored),
    )


def _confirmed(blocks: tuple[PlannedBlock, ...]) -> tuple[LoggedOutcome, ...]:
    """Every block confirmed as partly done, which is the one state carrying its own minutes."""
    return tuple(
        LoggedOutcome(
            block_id=block_id(WEEK, one.binding),
            state=OutcomeState.PARTIAL,
            actual_minutes=45,
            actual=None,
            is_confirmed=True,
        )
        for one in blocks
    )


def _lived(revision: StoredRevision) -> TenantCorpus:
    return corpus(revisions=[revision], outcomes=list(_confirmed(revision.blocks)))


class TestAWeekNobodyChoseIsInTheCorpus:
    def test_every_block_derived_fitter_reads_a_materialized_week(self) -> None:
        revision = _materialized(entries=_two_concrete_entries())

        observed = extract(_lived(revision))

        assert len(revision.blocks) == 2
        assert [len(observed.durations), len(observed.time_of_day), len(observed.skips)] == [
            2,
            2,
            2,
        ]
        assert len(observed.switches) == 1

    def test_an_unfilled_area_slot_supplies_nothing_a_fitter_can_count(self) -> None:
        # The bound on the row above, and the reason the inclusion is weak evidence rather than
        # wrong evidence: what a materialized week contributes is the entries the declarations fix.
        # A slot has no content and no identity a user could confirm, so it reaches no fitter.
        entries = (
            *_two_concrete_entries(),
            _entry(entry_id=SLOT_ENTRY, hour=14, kind=TemplateEntryKind.SLOT),
        )

        revision = _materialized(entries=entries)
        observed = extract(_lived(revision))

        assert len(_document(entries).empty_slots) == 1
        assert len(revision.blocks) == 2
        assert len(observed.time_of_day) == 2

    def test_the_plan_of_record_is_the_latest_revision_whatever_produced_it(self) -> None:
        # A solved week superseded by a materialization, which is the sequence the fallback path
        # produces: the week had a plan, a later solve failed terminally, and the plan of last
        # resort was appended over it. What the fitters read is the materialized one.
        solved = stored_revision(blocks=[planned(area_id=OTHER_AREA)], created_at=at(hour=0))
        latest = _materialized(entries=_two_concrete_entries(), hour=6)
        both = corpus(
            revisions=[solved, latest],
            outcomes=[outcome(), *_confirmed(latest.blocks)],
        )

        observed = extract(both)

        assert plans_of_record(both.revisions) == [latest]
        assert {one.area_id for one in observed.time_of_day} == {AREA}


class TestNothingTheCorpusReadsSaysWhatProducedARevision:
    def test_the_row_this_corpus_reads_says_what_produced_each_revision(self) -> None:
        # The crossing, and the reason the statement says the corpus DECLINES to narrow rather than
        # that it could not: the information is on the row it already reads. Which reasons that
        # column may carry is the api's own business and `test_horizon_maintainer.py` asserts it;
        # what matters here is only that the column exists to be read.
        assert set(PRODUCED_A_REVISION) <= set(PlanRevision.__table__.columns.keys())

    def test_the_revision_projection_carries_none_of_those_columns(self) -> None:
        fields = {one.name for one in dataclasses.fields(StoredRevision)}

        assert "created_at" in fields
        assert fields.isdisjoint(PRODUCED_A_REVISION)


class TestThePlanOfRecordStatementSaysWhatItAdmits:
    @pytest.mark.parametrize(
        "clause",
        [
            pytest.param("LATEST revision of each week, whatever produced it", id="the-rule"),
            pytest.param(
                "latest revision was materialized is therefore in the corpus",
                id="what-the-rule-admits",
            ),
            pytest.param("nobody chose its arrangement", id="why-it-matters"),
            pytest.param(
                "no objective was weighed and no user assented", id="what-nobody-chose-means"
            ),
            pytest.param("weaker evidence about what they prefer", id="what-such-a-week-is-worth"),
            pytest.param("It is kept rather than filtered", id="the-direction-decided"),
            pytest.param(
                "is a column on the row and is not in the projection this reads",
                id="why-it-could-not-be-filtered-here",
            ),
        ],
    )
    def test_the_statement_still_says(self, clause: str) -> None:
        assert features._lived_blocks.__doc__ is not None
        assert clause in " ".join(features._lived_blocks.__doc__.split())
