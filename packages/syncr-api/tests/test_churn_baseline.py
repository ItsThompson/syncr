"""The churn baseline an assembly produces, and what the objective prices from it.

Two halves of one seam, driven together. The assembler names the revision the user approved and
carries the plan that revision stored; ``syncr_solver.terms.churn`` reads that plan and prices how
far this week has moved from it. Neither half proves the pair: a producer test can assert that a
document arrived, a term test can assert that a document is priced, and every approved week can
still be priced at zero because the two are asserted against different values. So every case here
assembles a week from stored state and then evaluates a plan against what the assembly produced.

The fakes are the assembler suite's own and the weights are the shipped hand-tuned set, read
through the same adapter a solve reads it through, because a churn figure taken under invented
weights says nothing about what a user's week costs.

The repository is a fake, so the two revision reads cannot be put in disagreement here: a week
whose newest ``applied`` revision is newer than its newest ``approved`` one needs the real table,
and that case is asserted in the integration tier.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import pytest

from syncr_api.learned.config import P0_WEIGHTS
from syncr_api.learned.weight_reading import as_weight_set
from syncr_api.plans.stored_documents import stored_document
from syncr_common.logging import configure_logging
from syncr_solver.inputs import ChurnBaseline
from syncr_solver.objective import evaluate
from tests.assembly_fakes import (
    NOW,
    WEEK,
    FakeAreas,
    FakePlacements,
    FakeRevisions,
    a_plan,
    a_task_block,
    a_weight_set,
    an_approved_revision,
    an_area,
    an_assembler,
    at,
    between,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.core.columns import JsonObject
    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import SolveInputs

APPROVED_AT: Final = at(20, day=-1)

# The one Area every block here is charged to, registered with the assembly so the block reaches
# the objective with a budget behind it.
AREA: Final = an_area()

# What the churn term costs for one moved block under the shipped weights, derived by hand rather
# than by re-running the term's own arithmetic: one move against a tolerance of three is a third of
# the way to the knee, and the knee's shape is one over one plus the inverse squared, so 1/(1+9).
ONE_MOVE_UNDER_THE_SHIPPED_TOLERANCE: Final = 0.1

# A stored document naming no week, which every constructor in the document codec refuses. The
# shape a column holds after a write path that has since been corrected, rather than a shape a
# current writer can produce.
UNREBUILDABLE: Final[JsonObject] = {}

# The event the assembler emits when it cannot rebuild an approved plan.
UNREADABLE_EVENT: Final = "plans.churn_baseline.unreadable"


@pytest.fixture
def log_lines() -> Iterator[io.StringIO]:
    """Render every log line as the JSON a deployment collects, then hand the config back.

    Logging configuration is process-global, so the restore is what keeps this file from turning
    the strict event-name check off for whatever runs after it.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


def a_moved_pair() -> tuple[Block, Block]:
    """One task's block as the user approved it, and where the week now holds it.

    Same task and same chunk, so the two documents pair on the block's derived id and the
    difference between them is one MOVE. A different task would be a drop and an addition, and an
    addition is not churn.
    """
    task_id = uuid4()
    return (
        a_task_block(task_id=task_id, area_id=AREA.id, interval=between(10, 11, day=2)),
        a_task_block(task_id=task_id, area_id=AREA.id, interval=between(14, 15, day=2)),
    )


async def an_assembly(
    *, approved: PlanRevisionRecord | None, live_plan: PlanDocument | None = None
) -> SolveInputs:
    """One week assembled from stored state, holding ``approved`` as its only revision."""
    return await an_assembler(
        areas=FakeAreas([AREA]),
        revisions=FakeRevisions(approved),
        placements=FakePlacements(live_plan=live_plan),
    ).assemble(WEEK, NOW)


def cost_of_churn(plan: PlanDocument, inputs: SolveInputs) -> float:
    """What ``plan`` costs in churn for the week ``inputs`` describes, under the shipped weights."""
    return evaluate(plan, inputs=inputs, weights=as_weight_set(a_weight_set())).churn


# --------------------------------------------------------------------------------
# The three states
# --------------------------------------------------------------------------------


async def test_the_baseline_carries_the_plan_the_approved_revision_stored() -> None:
    approved_block, live_block = a_moved_pair()
    approved = a_plan(blocks=[approved_block])
    record = an_approved_revision(approved_at=APPROVED_AT, document=stored_document(approved))

    inputs = await an_assembly(approved=record, live_plan=a_plan(blocks=[live_block]))

    assert inputs.churn_baseline.reason == ChurnBaseline.APPROVED_REVISION
    assert inputs.churn_baseline.is_measured is True
    assert inputs.churn_baseline.revision_id == record.id
    assert inputs.churn_baseline.approved_at == APPROVED_AT
    # The plan the REVISION stored, rather than the plan the week now holds. The two differ by the
    # moved block, so an assembly handing the live plan over would satisfy the line above and fail
    # this one.
    assert inputs.churn_baseline.document == approved
    # And the week really does hold a different one, so the line above is a choice between two
    # documents rather than a comparison with nothing.
    assert inputs.live_plan == a_plan(blocks=[live_block])
    assert inputs.churn_baseline.document != inputs.live_plan


async def test_a_week_no_revision_of_which_was_approved_has_nothing_to_measure_against() -> None:
    inputs = await an_assembly(approved=None)

    assert inputs.churn_baseline.reason == ChurnBaseline.NEVER_APPROVED
    assert inputs.churn_baseline.revision_id is None
    assert inputs.churn_baseline.approved_at is None
    assert inputs.churn_baseline.document is None
    assert inputs.churn_baseline.is_measured is False


async def test_an_approved_plan_this_deployment_cannot_rebuild_reaches_the_third_state() -> None:
    # Degraded rather than raised, which is the choice stated beside the guard: the week is still
    # assembled and still solvable, with churn uncharged because there is nothing to charge it
    # against. The revision is still NAMED, which is what makes this state distinguishable from a
    # week nobody ever approved.
    record = an_approved_revision(approved_at=APPROVED_AT, document=UNREBUILDABLE)

    inputs = await an_assembly(approved=record)

    assert inputs.churn_baseline.reason == ChurnBaseline.APPROVED_UNREADABLE
    assert inputs.churn_baseline.revision_id == record.id
    assert inputs.churn_baseline.approved_at == APPROVED_AT
    assert inputs.churn_baseline.document is None
    assert inputs.churn_baseline.is_measured is False


async def test_a_plan_that_cannot_be_rebuilt_is_reported_rather_than_passed_over(
    log_lines: io.StringIO,
) -> None:
    # An unreadable approved document is a state an operator has to be able to find: the week
    # solves, the plan it produces is priced against nothing, and the only thing that says so is
    # this line. Read through the JSON a deployment collects rather than through a captured
    # intermediate.
    record = an_approved_revision(approved_at=APPROVED_AT, document=UNREBUILDABLE)

    await an_assembly(approved=record)

    reported = [
        line
        for line in (json.loads(text) for text in log_lines.getvalue().splitlines() if text)
        if line["event"] == UNREADABLE_EVENT
    ]
    assert len(reported) == 1, log_lines.getvalue()
    assert reported[0]["iso_week"] == str(WEEK)
    assert reported[0]["revision_id"] == str(record.id)
    assert reported[0]["level"] == "warning"
    # The document codec's own words, carried rather than replaced, so the line says WHICH part of
    # the stored plan could not be rebuilt.
    assert "iso_week" in reported[0]["refusal"]


async def test_a_readable_approved_plan_is_reported_nowhere(log_lines: io.StringIO) -> None:
    # The other edge of the report above. Without it, a guard that logged the refusal for every
    # approved week would pass the case that matters and say nothing.
    record = an_approved_revision(approved_at=APPROVED_AT, document=stored_document(a_plan()))

    await an_assembly(approved=record)

    events = [json.loads(text)["event"] for text in log_lines.getvalue().splitlines() if text]
    assert UNREADABLE_EVENT not in events
    assert "plans.assembly.completed" in events


# --------------------------------------------------------------------------------
# What the objective prices from it
# --------------------------------------------------------------------------------


async def test_a_week_whose_plan_moved_one_block_from_the_approved_one_costs_churn() -> None:
    approved_block, live_block = a_moved_pair()
    live = a_plan(blocks=[live_block])
    record = an_approved_revision(
        approved_at=APPROVED_AT, document=stored_document(a_plan(blocks=[approved_block]))
    )

    inputs = await an_assembly(approved=record, live_plan=live)

    assert cost_of_churn(live, inputs) == pytest.approx(
        P0_WEIGHTS["churn"] * ONE_MOVE_UNDER_THE_SHIPPED_TOLERANCE
    )


async def test_a_week_whose_plan_is_the_one_the_user_approved_costs_no_churn() -> None:
    # The arm that says the figure above comes from the DIFFERENCE between the two documents rather
    # than from a baseline merely carrying one. Same live plan shape, same weights, and the only
    # thing that changes is what the approved revision stored.
    approved_block, _ = a_moved_pair()
    live = a_plan(blocks=[approved_block])
    record = an_approved_revision(
        approved_at=APPROVED_AT, document=stored_document(a_plan(blocks=[approved_block]))
    )

    inputs = await an_assembly(approved=record, live_plan=live)

    assert inputs.churn_baseline.is_measured is True
    assert cost_of_churn(live, inputs) == 0.0


async def test_a_week_with_no_approved_revision_costs_no_churn_however_much_it_holds() -> None:
    # Not the same zero. Here there is nothing to compare against, and the baseline says so; above,
    # two documents were compared and agreed.
    _, live_block = a_moved_pair()
    live = a_plan(blocks=[live_block])

    inputs = await an_assembly(approved=None, live_plan=live)

    assert cost_of_churn(live, inputs) == 0.0
    assert inputs.churn_baseline.reason == ChurnBaseline.NEVER_APPROVED
