"""The composed read once every field has something in it, against a real Postgres.

Ticket 31 shipped six fields present and always empty and this is where they are filled, so what
this suite drives is the composition rather than any one collaborator. Five groups.

**Which verdict a read serves.** Note 6 of ``reviews/spec-review-5.md``, over rows rather than over
values: a week that passed the probe and then failed to PACK reports the packing failure while its
proposal is current, and falls back to a capacity check the moment approval clears the slot.
``13``'s route table says the read "computes a verdict for display", which would report the capacity
check forever; ``US-FEAS-02`` and ``S8`` both require the opposite, and the pending slot is the only
place a solver verdict is persisted.

**Neither branch writes anything.** Counted over every scoped table the application declares, on the
week whose slot is current and on the week whose slot is empty, so both code paths are measured. The
week's version is included in the comparison, because a read that bumped it would be a read that
invalidated a running solve and no row count would see it.

**Every other field, on one week at once.** A proposal, a candidate concession, two approved
concessions, a pin and a conflict, all on the week the maintainer planned. A composed read is
adversarial in exactly this state: five of the six fields are populated from five different tables.

**The pending proposal's own route**, which answers the slot or a 404, and answers one diff with the
composed read rather than a second shape of it.

**The boundaries a composed read has**: a week at the calendar's edge, a verdict read while a solve
is running, a conflict raised between two reads, a concession revoked between two reads, and the one
figure this payload spells twice today.

The backlog's half of the same arithmetic is ``test_at_risk_integration.py``, and the rows every
assertion here is driven against are ``tests/live_weeks.py``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from statistics import quantiles
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from syncr_api.approvals.config import APPROVE_PATH
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.plans.config import PENDING_PROPOSALS_TABLE
from syncr_api.solving.config import SOLVE
from syncr_domain.feasibility import Provenance, ShortfallKind
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import provision_owner, remove_tenant, row_counts
from tests.live_weeks import (
    BLOCKS_IN_A_FULL_WEEK,
    LONDON,
    UNPLACEABLE,
    a_candidate_moving_one_block,
    a_packing_failure,
    append_a_full_week,
    approve_two_concessions,
    declare_the_minimum,
    enqueue_a_solve,
    fill_the_slot,
    hold_a_pin,
    produce_a_plan,
    raise_a_conflict,
    set_home_zone,
    sign_in,
    the_live_plan,
    the_weeks_version,
    this_week,
    week_path,
    week_view,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

# How many reads the p95 is taken over, and the ceiling this suite fails at. The budget is p95 under
# 300 ms; the ceiling here is deliberately looser, because a developer's machine and a CI runner are
# not the deployment, and the measured figure is reported rather than asserted.
LATENCY_SAMPLES = 30
CATASTROPHIC_MILLISECONDS = 1000


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    """A client against an app wired to the live database, as the process wires it."""
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def configured(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> tuple[dict[str, str], str]:
    """A signed-in tenant in London that has declared what a plan needs, and its Area."""
    headers = sign_in(http, owner.email)
    set_home_zone(http, headers, LONDON)
    return headers, declare_the_minimum(http, headers, live_database_url, owner.tenant_id)


# --------------------------------------------------------------------------------
# Which verdict a read serves
# --------------------------------------------------------------------------------


@pytest.fixture
def a_week_whose_solve_failed_to_pack(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> tuple[dict[str, str], IsoWeek]:
    """A week that passed the probe, then failed to pack, and holds the proposal that says so."""
    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)
    live = the_live_plan(live_database_url, owner.tenant_id, week)
    version = the_weeks_version(live_database_url, owner.tenant_id, week)
    document, diff = a_candidate_moving_one_block(live)
    fill_the_slot(
        live_database_url,
        owner.tenant_id,
        week,
        verdict=a_packing_failure(
            input_version=version, deadline=datetime.now(UTC) + timedelta(days=2)
        ),
        document=document,
        diff=diff,
        input_version=version,
        operation_id=enqueue_a_solve(live_database_url, owner.tenant_id, week),
    )
    return headers, week


def test_a_week_holding_a_current_proposal_reports_the_solves_stronger_finding(
    http: TestClient, a_week_whose_solve_failed_to_pack: tuple[dict[str, str], IsoWeek]
) -> None:
    """``US-FEAS-02``: the stronger finding replaces the reading once the solve lands.

    ``13``'s route table says this read computes a verdict, which would answer ``probe`` here and
    lose the packing failure entirely. The finding is one no capacity arithmetic can produce, so its
    presence is what proves the slot was served rather than a fresh probe.
    """
    headers, week = a_week_whose_solve_failed_to_pack

    verdict = week_view(http, headers, week)["verdict"]

    assert verdict["provenance"] == Provenance.SOLVER.value
    assert [gap["kind"] for gap in verdict["shortfalls"]] == [
        ShortfallKind.MINIMUM_CHUNK_UNPLACEABLE.value
    ]
    assert verdict["shortfalls"][0]["against"] == [UNPLACEABLE]


def test_the_earlier_reading_is_stated_to_have_been_a_capacity_check(
    http: TestClient, a_week_whose_solve_failed_to_pack: tuple[dict[str, str], IsoWeek]
) -> None:
    """The other half of the criterion, and it is the two fields rather than a sentence.

    ``feasible`` and ``capacityIsSufficient`` are two claims: the served verdict is authoritative,
    so a surface renders ``feasible``, and the ``provenance`` beside it is what says the earlier
    reading was arithmetic. A probe verdict cannot say either, which is what the fallback below
    reports.
    """
    headers, week = a_week_whose_solve_failed_to_pack

    verdict = week_view(http, headers, week)["verdict"]

    assert verdict["feasible"] is False
    assert verdict["capacityIsSufficient"] is False
    assert verdict["provenance"] == Provenance.SOLVER.value


def test_clearing_the_slot_by_approving_falls_back_to_a_live_probe_verdict(
    http: TestClient,
    owner: UserRecord,
    a_week_whose_solve_failed_to_pack: tuple[dict[str, str], IsoWeek],
) -> None:
    """The slot is the only place a solver verdict lives, and approval empties it.

    Approving also bumps the version, so both halves of the currency test change at once: the row is
    gone and the figure it would have been compared against has moved.
    """
    headers, week = a_week_whose_solve_failed_to_pack
    before = week_view(http, headers, week)["verdict"]["provenance"]

    approved = http.post(
        f"{WEEKS_PREFIX}{APPROVE_PATH.replace('{iso_week}', str(week))}",
        headers={**headers, IDEMPOTENCY_KEY_HEADER: str(uuid4())},
    )

    assert approved.status_code == HTTPStatus.CREATED, approved.text
    assert before == Provenance.SOLVER.value
    after = week_view(http, headers, week)["verdict"]
    assert after["provenance"] == Provenance.PROBE.value
    assert after["feasible"] is False, "a probe verdict may never claim a week works"


def test_a_proposal_the_week_has_moved_past_is_not_served_as_the_weeks_verdict(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """A slot behind the week describes an input state the week no longer holds.

    This is what a mutation leaves behind: the version moved and the proposal did not, so its
    verdict is a fact about something else and the read computes one about the week as it stands.
    """
    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)
    live = the_live_plan(live_database_url, owner.tenant_id, week)
    version = the_weeks_version(live_database_url, owner.tenant_id, week)
    document, diff = a_candidate_moving_one_block(live)
    fill_the_slot(
        live_database_url,
        owner.tenant_id,
        week,
        verdict=a_packing_failure(
            input_version=version - 1, deadline=datetime.now(UTC) + timedelta(days=2)
        ),
        document=document,
        diff=diff,
        input_version=version - 1,
        operation_id=enqueue_a_solve(live_database_url, owner.tenant_id, week),
    )

    view = week_view(http, headers, week)
    refreshed = http.get(week_path(week, "/verdict"), headers=headers)

    assert view["verdict"]["provenance"] == Provenance.PROBE.value
    assert view["proposal"] is not None, "the stale proposal is still rendered as a proposal"
    assert view["inputVersion"] == version
    # The cheap refresh applies the currency test too, or the strip and the panel would report two
    # provenances for one week: the composed read alone would leave that half of the rule untested.
    assert refreshed.status_code == HTTPStatus.OK, refreshed.text
    assert refreshed.json()["verdict"]["provenance"] == Provenance.PROBE.value


def test_the_cheap_refresh_serves_the_same_verdict_the_composed_read_does(
    http: TestClient, a_week_whose_solve_failed_to_pack: tuple[dict[str, str], IsoWeek]
) -> None:
    """One rule, so the strip and the panel cannot report different provenance for one week.

    Compared whole on this branch, because a stored verdict is a value rather than a computation:
    the two routes read one row, so every field including the instant it names is equal.
    """
    headers, week = a_week_whose_solve_failed_to_pack

    refreshed = http.get(week_path(week, "/verdict"), headers=headers)

    assert refreshed.status_code == HTTPStatus.OK, refreshed.text
    assert refreshed.json()["verdict"] == week_view(http, headers, week)["verdict"]


def test_the_cheap_refresh_agrees_with_the_composed_read_on_the_live_branch_too(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """The branch that COMPUTES, where the agreement is the one that could fail.

    Two requests are two instants, so the instant each verdict was computed at differs by design
    and is the one field excluded. Everything the panel and the strip render is compared: a second
    reading of the rule would show as a different provenance, a different gap, or a different
    denominator.
    """
    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)

    refreshed = http.get(week_path(week, "/verdict"), headers=headers)

    assert refreshed.status_code == HTTPStatus.OK, refreshed.text
    served = refreshed.json()["verdict"]
    composed = week_view(http, headers, week)["verdict"]
    assert served["provenance"] == Provenance.PROBE.value, "this asserted the stored branch again"
    assert served["computedAt"] != composed["computedAt"], (
        "two requests reported one instant, so the clock is not the one production reads"
    )
    assert _without_its_instant(served) == _without_its_instant(composed)


def _without_its_instant(verdict: dict[str, Any]) -> dict[str, Any]:
    """One verdict with the instant it was computed at removed, and nothing else."""
    return {name: value for name, value in verdict.items() if name != "computedAt"}


def test_a_week_with_no_plan_has_no_verdict_and_one_with_a_plan_has_one(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """The biconditional, over the same tenant at two weeks so nothing else differs."""
    headers, _area_id = configured
    beyond = IsoWeek.containing(datetime.now(UTC).date() + timedelta(days=60))
    produce_a_plan(live_database_url, owner.tenant_id, this_week())

    planned = week_view(http, headers, this_week())
    empty = week_view(http, headers, beyond)

    assert (planned["live"] is None) == (planned["verdict"] is None) is False
    assert (empty["live"] is None) == (empty["verdict"] is None) is True


# --------------------------------------------------------------------------------
# Neither branch writes anything
# --------------------------------------------------------------------------------


def test_neither_verdict_branch_writes_a_row_or_moves_the_weeks_version(
    http: TestClient,
    owner: UserRecord,
    a_week_whose_solve_failed_to_pack: tuple[dict[str, str], IsoWeek],
    live_database_url: str,
    source_root: Path,
) -> None:
    """Both branches, in one test, because a guard over one of two paths covers half the rule.

    The version is compared as well as the row counts: a bump writes no row a count would catch, and
    a read that bumped would invalidate a running solve.
    """

    headers, week = a_week_whose_solve_failed_to_pack
    served = week_view(http, headers, week)["verdict"]["provenance"]
    before = row_counts(live_database_url, owner.tenant_id, source_root)
    version = the_weeks_version(live_database_url, owner.tenant_id, week)

    for _ in range(2):
        assert week_view(http, headers, week)["verdict"] is not None
        assert http.get(week_path(week, "/verdict"), headers=headers).status_code == HTTPStatus.OK
        assert http.get(week_path(week, "/proposal"), headers=headers).status_code == HTTPStatus.OK

    assert served == Provenance.SOLVER.value, "the slot branch was not the one measured"
    assert row_counts(live_database_url, owner.tenant_id, source_root) == before
    assert the_weeks_version(live_database_url, owner.tenant_id, week) == version


def test_the_live_probe_branch_writes_nothing_either(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
    source_root: Path,
) -> None:
    """The branch that ASSEMBLES, which is the one with something to write if anything did."""

    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)
    before = row_counts(live_database_url, owner.tenant_id, source_root)
    version = the_weeks_version(live_database_url, owner.tenant_id, week)

    for _ in range(2):
        assert week_view(http, headers, week)["verdict"]["provenance"] == Provenance.PROBE.value

    assert row_counts(live_database_url, owner.tenant_id, source_root) == before
    assert the_weeks_version(live_database_url, owner.tenant_id, week) == version


# --------------------------------------------------------------------------------
# Every other field, on one week at once
# --------------------------------------------------------------------------------


@pytest.fixture
def a_week_holding_everything(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> tuple[dict[str, str], IsoWeek, dict[str, Any]]:
    """A week with a plan, a proposal, a candidate, two concessions, a pin, and a conflict."""
    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)
    live = the_live_plan(live_database_url, owner.tenant_id, week)
    version = the_weeks_version(live_database_url, owner.tenant_id, week)
    operation_id = enqueue_a_solve(live_database_url, owner.tenant_id, week)
    candidate: dict[str, Any] = {
        "adjustmentId": str(uuid4()),
        "kind": AdjustmentKind.ACCEPT_PARTIAL.value,
        "targetId": str(uuid4()),
        "reductions": {},
        "deltaMinutes": None,
    }
    document, diff = a_candidate_moving_one_block(live)
    fill_the_slot(
        live_database_url,
        owner.tenant_id,
        week,
        verdict=a_packing_failure(
            input_version=version, deadline=datetime.now(UTC) + timedelta(days=2)
        ),
        document=document,
        diff=diff,
        input_version=version,
        operation_id=operation_id,
        candidate=candidate,
    )
    approved = approve_two_concessions(
        live_database_url, owner.tenant_id, week, operation_id=operation_id
    )
    pin_id = hold_a_pin(live_database_url, owner.tenant_id, week, live.blocks[0])
    conflict_id = raise_a_conflict(live_database_url, owner.tenant_id, week, live.blocks[1])
    return (
        headers,
        week,
        {
            "adjustments": approved,
            "candidate": candidate,
            "pin": pin_id,
            "conflict": conflict_id,
            "moved": live.blocks[0].id,
        },
    )


def test_every_field_of_the_composed_read_carries_what_it_names(
    http: TestClient, a_week_holding_everything: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """Six fields from five tables in one payload, the state a composed read is hardest in."""
    headers, week, seeded = a_week_holding_everything

    view = week_view(http, headers, week)

    assert [change["blockId"] for change in view["proposal"]["moved"]] == [seeded["moved"]]
    assert view["proposal"]["added"] == []
    assert view["candidateAdjustment"]["id"] == seeded["candidate"]["adjustmentId"]
    assert sorted(one["id"] for one in view["adjustments"]) == sorted(seeded["adjustments"])
    assert [one["id"] for one in view["pins"]] == [seeded["pin"]]
    assert [one["id"] for one in view["conflicts"]] == [seeded["conflict"]]
    assert view["verdict"]["provenance"] == Provenance.SOLVER.value


def test_a_week_that_absorbed_two_concessions_reports_both_of_them(
    http: TestClient, a_week_holding_everything: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """A week that has absorbed a concession must not read as simply feasible.

    The panel lists them above the shortfalls, so the read has to carry every one the week holds: a
    week reporting one of two would report a healthy week for a reason the user cannot see.
    """
    headers, week, seeded = a_week_holding_everything

    listed = week_view(http, headers, week)["adjustments"]

    assert len(listed) == 2
    assert {one["kind"] for one in listed} == {
        AdjustmentKind.BREACH_FLOOR.value,
        AdjustmentKind.REDUCE_ROUTINE.value,
    }
    assert sorted(one["id"] for one in listed) == sorted(seeded["adjustments"])


def test_the_candidate_concession_carries_the_identifier_the_approval_will_persist(
    http: TestClient, a_week_holding_everything: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """One concession with one identity, whether the user assented to it or is being asked to."""
    headers, week, seeded = a_week_holding_everything

    candidate = week_view(http, headers, week)["candidateAdjustment"]

    assert candidate["id"] == seeded["candidate"]["adjustmentId"]
    assert candidate["kind"] == AdjustmentKind.ACCEPT_PARTIAL.value
    assert candidate["isoWeek"] == str(week)
    assert candidate["id"] not in seeded["adjustments"], "the candidate is not one the week holds"


def test_a_concession_revoked_between_two_reads_leaves_the_second_reporting_one(
    http: TestClient,
    owner: UserRecord,
    a_week_holding_everything: tuple[dict[str, str], IsoWeek, dict[str, Any]],
) -> None:
    """The week's concessions are read per request, so a revocation is visible on the next read."""
    headers, week, seeded = a_week_holding_everything
    revoked, kept = seeded["adjustments"]

    answered = http.delete(
        f"{WEEKS_PREFIX}/{week}/adjustments/{revoked}",
        headers={**headers, IDEMPOTENCY_KEY_HEADER: str(uuid4())},
    )

    assert answered.status_code == HTTPStatus.NO_CONTENT, answered.text
    assert [one["id"] for one in week_view(http, headers, week)["adjustments"]] == [kept]


# --------------------------------------------------------------------------------
# The pending proposal's own route
# --------------------------------------------------------------------------------


def test_reading_the_proposal_of_a_week_with_an_empty_slot_is_a_404(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """A slot with at most one occupant is an absent resource when it holds none."""
    headers, _area_id = configured
    produce_a_plan(live_database_url, owner.tenant_id, this_week())

    answered = http.get(week_path(this_week(), "/proposal"), headers=headers)

    assert answered.status_code == HTTPStatus.NOT_FOUND, answered.text


def test_reading_the_proposal_answers_the_diff_the_verdict_and_the_candidate(
    http: TestClient, a_week_holding_everything: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    headers, week, seeded = a_week_holding_everything

    answered = http.get(week_path(week, "/proposal"), headers=headers)

    assert answered.status_code == HTTPStatus.OK, answered.text
    held = answered.json()
    assert held["isoWeek"] == str(week)
    assert [change["blockId"] for change in held["proposal"]["moved"]] == [seeded["moved"]]
    assert held["verdict"]["provenance"] == Provenance.SOLVER.value
    assert held["candidateAdjustment"]["id"] == seeded["candidate"]["adjustmentId"]
    assert held["inputVersion"] == week_view(http, headers, week)["inputVersion"]


def test_the_proposal_route_and_the_composed_read_answer_one_diff(
    http: TestClient, a_week_holding_everything: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """Two routes, one rebuild, so a client cannot see two shapes of one proposal."""
    headers, week, _seeded = a_week_holding_everything

    answered = http.get(week_path(week, "/proposal"), headers=headers)

    assert answered.json()["proposal"] == week_view(http, headers, week)["proposal"]


def test_approving_the_proposal_makes_its_own_route_a_404(
    http: TestClient, a_week_whose_solve_failed_to_pack: tuple[dict[str, str], IsoWeek]
) -> None:
    """Approval clears the slot, so the resource is gone rather than emptied."""
    headers, week = a_week_whose_solve_failed_to_pack
    assert http.get(week_path(week, "/proposal"), headers=headers).status_code == HTTPStatus.OK

    approved = http.post(
        f"{WEEKS_PREFIX}{APPROVE_PATH.replace('{iso_week}', str(week))}",
        headers={**headers, IDEMPOTENCY_KEY_HEADER: str(uuid4())},
    )

    assert approved.status_code == HTTPStatus.CREATED, approved.text
    assert http.get(week_path(week, "/proposal"), headers=headers).status_code == (
        HTTPStatus.NOT_FOUND
    )


# --------------------------------------------------------------------------------
# The boundaries a composed read has: the calendar, a running solve, a mid-read change
# --------------------------------------------------------------------------------


def test_the_last_week_of_a_year_that_has_fifty_three_carries_a_verdict_like_any_other(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """2026 has a week 53, and a verdict is computed from an assembly of it like any other week.

    The week is written rather than materialized, because no horizon reaches December from here:
    what is under test is that the composed read assembles and probes a week at the calendar's edge.
    """
    headers, _area_id = configured
    last = IsoWeek.parse("2026-W53")
    append_a_full_week(live_database_url, owner.tenant_id, last)

    view = week_view(http, headers, last)

    assert view["isoWeek"] == str(last)
    assert view["verdict"] is not None
    assert view["verdict"]["provenance"] == Provenance.PROBE.value
    assert view["verdict"]["discretionaryMinutes"] > 0


def test_a_week_with_a_solve_in_flight_still_answers_its_verdict(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """A verdict read while a solve runs is a read of the week as it stands, not a wait.

    The strip reports the plan as being recomputed and the verdict beside it is still the honest
    reading of the inputs the week holds now: a verdict withheld until a solve landed would leave
    the panel empty for the two seconds a user is most likely to be looking at it.
    """
    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)
    enqueue_a_solve(live_database_url, owner.tenant_id, week)

    view = week_view(http, headers, week)

    assert view["readings"]["planCurrency"] == "solving"
    assert view["operation"]["kind"] == SOLVE
    assert view["verdict"] is not None


def test_a_conflict_raised_between_two_reads_appears_on_the_second(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """The conflicts are read per request, which is what makes the banner current without a push.

    A conflict is the one condition in this product that notifies, and the notification is the
    stream's business; what the composed read owes is that the next read of the week holds it.
    """
    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)
    live = the_live_plan(live_database_url, owner.tenant_id, week)
    assert week_view(http, headers, week)["conflicts"] == []

    raised = raise_a_conflict(live_database_url, owner.tenant_id, week, live.blocks[1])

    conflicts = week_view(http, headers, week)["conflicts"]
    assert [one["id"] for one in conflicts] == [raised]
    assert conflicts[0]["resolvedAt"] is None
    assert conflicts[0]["blockId"] == live.blocks[1].id


def test_the_composed_read_selects_the_pending_slot_exactly_once(
    owner: UserRecord, live_database_url: str, settings: ServiceSettings
) -> None:
    """One statement, so one snapshot, so the proposal and the verdict describe one slot state.

    The request runs in one transaction under ``READ COMMITTED``, so two statements reading the slot
    take two snapshots: an approval landing between them would answer with a proposal to assent to
    beside a verdict computed as though the slot were empty, and the same concession could appear
    twice under one identifier, once awaiting assent and once granted.

    Counted at the driver rather than by reading the source, because the second read was inside a
    collaborator and a source-level check would have to know which collaborators read what. The
    statement text is matched on the table, so the count survives any rewording of the query.
    """
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    selects: list[str] = []

    @event.listens_for(database.engine.sync_engine, "after_cursor_execute")
    def _count(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
        if PENDING_PROPOSALS_TABLE in statement and statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    with TestClient(app, raise_server_exceptions=False) as client:
        headers = sign_in(client, owner.email)
        set_home_zone(client, headers, LONDON)
        declare_the_minimum(client, headers, live_database_url, owner.tenant_id)
        week = this_week()
        produce_a_plan(live_database_url, owner.tenant_id, week)
        live = the_live_plan(live_database_url, owner.tenant_id, week)
        version = the_weeks_version(live_database_url, owner.tenant_id, week)
        document, diff = a_candidate_moving_one_block(live)
        fill_the_slot(
            live_database_url,
            owner.tenant_id,
            week,
            verdict=a_packing_failure(
                input_version=version, deadline=datetime.now(UTC) + timedelta(days=2)
            ),
            document=document,
            diff=diff,
            input_version=version,
            operation_id=enqueue_a_solve(live_database_url, owner.tenant_id, week),
        )
        selects.clear()

        view = week_view(client, headers, week)

    assert view["proposal"] is not None, "the slot was empty, so the read took the cheap branch"
    assert view["verdict"]["provenance"] == Provenance.SOLVER.value
    assert len(selects) == 1, selects


def test_the_two_denominators_on_one_payload_differ_by_the_occupancy_the_budget_cannot_see(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """One payload spells the denominator twice today, and the difference is measured rather than
    left implicit.

    ``readings.discretionaryMinutes`` is the budget report's and ``verdict.discretionaryMinutes``
    is the probe's. The probe subtracts all four subtrahends and the budget's occupancy reader fills
    one, so the budget's figure is the whole span on a week with a circadian frame. The honest
    figure is the verdict's.

    Pinned side by side the way the pie review's own crossing is: the seam that closes it is ticket
    1310's and it moves both figures at once, so this reddens on the commit that lands it and is
    deleted with the difference.
    """
    headers, _area_id = configured
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)

    view = week_view(http, headers, week)

    strip = view["readings"]["discretionaryMinutes"]
    probed = view["verdict"]["discretionaryMinutes"]
    assert probed < strip, (probed, strip)
    assert strip - probed >= 3360, "the frame this week sleeps for is 56 hours"


# --------------------------------------------------------------------------------
# The budget, measured
# --------------------------------------------------------------------------------


def test_the_composed_read_is_well_under_the_budget_with_every_field_populated(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """p95 under 300 ms on roughly 210 blocks, measured rather than asserted.

    Measured on the branch that pays for a live probe, because that is the one that assembles: a
    week whose slot is current serves a stored verdict and is the cheaper of the two. The suite's
    own ceiling is an order of magnitude looser than the budget, because a developer's machine is
    not the deployment, and the figure is reported.
    """
    headers, _area_id = configured
    week = this_week()
    append_a_full_week(live_database_url, owner.tenant_id, week)
    approve_two_concessions(
        live_database_url,
        owner.tenant_id,
        week,
        operation_id=enqueue_a_solve(live_database_url, owner.tenant_id, week),
    )
    live = the_live_plan(live_database_url, owner.tenant_id, week)
    hold_a_pin(live_database_url, owner.tenant_id, week, live.blocks[0])
    raise_a_conflict(live_database_url, owner.tenant_id, week, live.blocks[1])
    populated = week_view(http, headers, week)
    assert len(populated["live"]["blocks"]) == BLOCKS_IN_A_FULL_WEEK
    assert populated["verdict"] is not None
    assert populated["adjustments"] and populated["pins"] and populated["conflicts"]

    elapsed = []
    for _ in range(LATENCY_SAMPLES):
        started = time.perf_counter()
        answered = http.get(week_path(week), headers=headers)
        elapsed.append((time.perf_counter() - started) * 1000)
        assert answered.status_code == HTTPStatus.OK, answered.text

    ordered = sorted(elapsed)
    p95 = quantiles(ordered, n=20)[-1]
    print(
        f"\nGET /weeks/{{iso_week}} with every field populated over {LATENCY_SAMPLES} reads: "
        f"p50 {ordered[len(ordered) // 2]:.1f} ms, p95 {p95:.1f} ms, max {ordered[-1]:.1f} ms"
    )

    assert p95 < CATASTROPHIC_MILLISECONDS, ordered
