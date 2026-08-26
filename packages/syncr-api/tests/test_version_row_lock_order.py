"""The seventeen version-row callers, each accounted against the lock-order rule.

The rule, stated on :meth:`~syncr_api.plans.versions.WeekInputVersionRepository.hold`:
whoever takes the week's input-version row takes it FIRST. It is the one lock this api holds
across several writes, so the order two transactions take their rows in is decided entirely by
where this one sits; a caller that writes another table before taking it inverts the order
against every caller that does not, and two such transactions deadlock. One inversion was
fixed that way once already (the concession revoke that removed its adjustment before taking
the row); this walk is what keeps the rest of the tree from drifting into the same shape, and
what bites when an eighteenth caller arrives disobeying.

**Both halves are derived, neither is listed.** :mod:`tests.version_row_census` discovers the
callers off the source and reads the ordering off the function bodies, so a new caller shows
up here without anyone remembering. What IS listed is the resolution of every site the walk
flags today: a caller whose writes sit outside the function its take lives in, or whose
pre-take write cannot contend with a version-first writer, carries that reason inline below.
A flagged site with no resolution fails here, and so does a resolution whose site has gone --
both directions rot otherwise.

**One finding is recorded rather than fixed.** ``PinService.unpin`` releases the pin row
before bumping the week, which is the inverted shape the rule names: a pin written first here
can cycle against a caller that takes the row and then pins. This ticket measures the tree and
changes no service's write order, so the inversion stands resolved-as-recorded below, stated
where a follow-up that reorders it will delete the entry and watch the walk go green.

Both controls plant a synthetic module shaped like a real caller: one that writes first and
must redden the walk, one that takes the row first and must stay green. A reading never seen
to fail cannot be trusted to fail when the thing it guards arrives.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import syncr_api
from tests.version_row_census import (
    lock_order_violations,
    version_row_calls,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# The real tree both readings stand over, resolved from the installed module rather than cwd.
SOURCE_ROOT = Path(syncr_api.__file__).resolve().parent

# How many callers exist today. When this moves, a caller arrived or left: find it, decide
# whether it obeys the rule, and record it in the same change that moves the figure.
MEASURED_CALLERS = 17

# Every call site the walk must find, keyed without the line a formatting change moves.
EXPECTED_CALLERS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("anchors/reconcile.py", "AnchorReconciler._invalidate", "bump"),
        ("approvals/service.py", "ApprovalService._written", "bump"),
        ("approvals/service.py", "ApprovalService.approve", "hold"),
        ("calendars/service.py", "CalendarSourceService._bump_covered_weeks", "bump"),
        ("concessions/service.py", "ConcessionService.revoke", "bump"),
        ("concessions/service.py", "ConcessionService.revoke", "hold"),
        ("conflicts/service.py", "ConflictService._solve_for", "bump"),
        ("learned/activation.py", "FutureWeeksResolved._resolved", "bump"),
        ("offplan/service.py", "OffPlanService._bump", "bump"),
        ("pins/service.py", "PinService._held", "bump"),
        ("pins/service.py", "PinService.unpin", "bump"),
        ("plans/production.py", "WeekProducer._produce_week", "bump"),
        ("solving/dispatch.py", "SolveDispatch._adopted", "bump"),
        ("user_settings/service.py", "SettingsService._bump_for", "bump"),
        ("user_settings/service.py", "SettingsService.update", "bump"),
        ("user_settings/solve_inputs.py", "BacklogWideBump.from_the_week_holding", "bump"),
        ("user_settings/solve_inputs.py", "TrackedWeekInputVersions.bump", "bump"),
    }
)

# The sites the walk flags, each resolved with the reason it is not an unordered write.
RESOLVED_PRECEDING_WRITES: Mapping[tuple[str, str], str] = {
    # The take happens above this helper: `approve`, the one entrypoint that reaches it,
    # holds the row before anything is read, and every write below answers to that hold.
    ("approvals/service.py", "ApprovalService._written"): (
        "the row is taken by the calling entrypoint (`approve`) before this transaction's "
        "writes run"
    ),
    # Its pre-take write inserts a revision row nothing else locks: new rows conflict with
    # nothing, and the producer cannot reach a week that holds a pending proposal or a live
    # revision, so no version-first writer contends on that table.
    ("plans/production.py", "WeekProducer._produce_week"): (
        "the earlier write inserts a fresh revision row nothing else acquires, and this path "
        "cannot reach a week whose row another caller could hold"
    ),
    # Ordered on the settings row instead: that row is taken FOR UPDATE before it is written,
    # and no caller anywhere takes the version row first and then writes settings.
    ("user_settings/service.py", "SettingsService.update"): (
        "ordered on the settings row itself, locked FOR UPDATE before the write; no "
        "version-first writer of the settings table exists"
    ),
    # THE FINDING. Release precedes bump: the inverted shape the rule names. Recorded, not
    # reordered -- this ticket changes no service's write order. Reordering it deletes this
    # entry and the walk stays green.
    ("pins/service.py", "PinService.unpin"): (
        "RECORDED INVERSION: the pin row is released before the week's row is bumped; left "
        "as found because this walk measures write order and changes none"
    ),
}


def test_the_walk_finds_the_seventeen_call_sites_that_exist() -> None:
    calls = version_row_calls(SOURCE_ROOT)
    assert len(calls) == MEASURED_CALLERS
    found = {call.site for call in calls}
    surprise = found - EXPECTED_CALLERS
    missing = EXPECTED_CALLERS - found
    assert not surprise, f"a caller arrived without being recorded here: {sorted(surprise)}"
    assert not missing, f"a recorded caller is gone from the tree: {sorted(missing)}"


def test_every_preceding_write_carries_a_recorded_resolution() -> None:
    violations = lock_order_violations(SOURCE_ROOT)
    unresolved = {
        violation.site: violation.called
        for violation in violations
        if violation.site not in RESOLVED_PRECEDING_WRITES
    }
    stale = set(RESOLVED_PRECEDING_WRITES) - {violation.site for violation in violations}
    assert not unresolved, (
        "a caller writes another table before taking the version row, which deadlocks "
        f"against a caller that takes it first; resolve it or record why it cannot contend: "
        f"{unresolved}"
    )
    assert not stale, f"a resolution names a site the walk no longer flags: {sorted(stale)}"


def test_control_a_fixture_caller_that_writes_first_reddens_the_walk(tmp_path: Path) -> None:
    root = _plant(tmp_path / "red", "fixture_writer.py", _FIXTURE_THAT_WRITES_FIRST)
    violations = lock_order_violations(root)
    assert len(violations) == 1
    flagged = violations[0]
    assert flagged.site == ("fixture_writer.py", "UnpinFixture.unpin")
    assert flagged.called == "self._pins.release"
    assert flagged.collaborator == "PinRepository"
    # The walk saw the take too: the site is counted, and ordered against the write.
    assert [call.site for call in version_row_calls(root)] == [
        ("fixture_writer.py", "UnpinFixture.unpin", "bump")
    ]


def test_control_a_fixture_caller_that_takes_the_row_first_stays_green(tmp_path: Path) -> None:
    root = _plant(tmp_path / "green", "fixture_taker.py", _FIXTURE_THAT_TAKES_FIRST)
    assert lock_order_violations(root) == ()
    assert [call.site for call in version_row_calls(root)] == [
        ("fixture_taker.py", "UnpinFixture.unpin", "bump")
    ]


def _plant(root: Path, name: str, source: str) -> Path:
    """A synthetic source root carrying exactly one module, shaped like a real caller."""
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(source, encoding="utf-8")
    return root


_FIXTURE_THAT_WRITES_FIRST = """\
class PinRepository:
    async def release(self, pin_id: str) -> bool:
        return True


class WeekInputVersionRepository:
    async def bump(self, iso_week: str, *, at: str) -> int:
        return 1


_PIN = "pin"
_WEEK = "2026-W07"
_NOW = "now"


class UnpinFixture:
    def __init__(self, pins: PinRepository, versions: WeekInputVersionRepository) -> None:
        self._pins = pins
        self._versions = versions

    async def unpin(self) -> None:
        await self._pins.release(_PIN)
        await self._versions.bump(_WEEK, at=_NOW)
"""

_FIXTURE_THAT_TAKES_FIRST = """\
class PinRepository:
    async def release(self, pin_id: str) -> bool:
        return True


class WeekInputVersionRepository:
    async def bump(self, iso_week: str, *, at: str) -> int:
        return 1


_PIN = "pin"
_WEEK = "2026-W07"
_NOW = "now"


class UnpinFixture:
    def __init__(self, pins: PinRepository, versions: WeekInputVersionRepository) -> None:
        self._pins = pins
        self._versions = versions

    async def unpin(self) -> None:
        await self._versions.bump(_WEEK, at=_NOW)
        await self._pins.release(_PIN)
"""
