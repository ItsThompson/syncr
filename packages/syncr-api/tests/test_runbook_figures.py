"""The figures the two operation runbooks quote, crossed against the code that decides them.

A runbook is read once, under pressure, by someone deciding whether to intervene. One whose numbers
have drifted from the deployment is worse than none: it will be trusted, and it will be wrong. So
every figure these two quote is asserted against the constant that produces it, rather than against
a second copy of the number here.

The prose claims are asserted too, and each is one the ticket requires the runbook to make. They are
matched as substrings rather than by structure, because what has to survive is the STATEMENT: an
operator searching the file for "lease" has to find what the lease is.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from syncr_api.calendars.google_config import WRITE_DEADLINE_SECONDS
from syncr_api.calendars.injection import UNARMED
from syncr_api.calendars.projection_errors import ProjectionFailed, ProjectionRefused
from syncr_api.calendars.projection_notices import PROJECTION_STOPPED
from syncr_api.calendars.projection_runner import TENANT_PROJECTION_FAILURES
from syncr_api.calendars.schemas import SyncStateResponse
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS
from syncr_api.google_account.models import GoogleCredential
from syncr_api.google_account.notices import WRITE_TARGET_EXPIRED
from syncr_api.solving.config import (
    FAILED_RETENTION,
    LEASE,
    LEASE_EXPIRED,
    MAX_ATTEMPTS,
    RETRY_BACKOFF,
    SUCCEEDED_RETENTION,
)
from syncr_api.solving.config import SUPERSEDED as SUPERSEDED_STATUS
from syncr_api.solving.maintenance import MAINTENANCE_INTERVAL
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from datetime import timedelta

RUNBOOKS: Final = Path(__file__).resolve().parents[3] / "docs" / "runbooks"

STUCK_OPERATION = RUNBOOKS / "stuck-operation.md"
SOLVE_FAILING = RUNBOOKS / "solve-failing.md"
DEBOUNCE_TUNING = RUNBOOKS / "debounce-tuning.md"
GOOGLE_TOKEN_EXPIRED = RUNBOOKS / "google-token-expired.md"


def read(runbook: Path) -> str:
    assert runbook.is_file(), f"{runbook} does not exist"
    return runbook.read_text(encoding="utf-8")


def minutes(value: timedelta) -> int:
    return int(value.total_seconds() // 60)


def days(value: timedelta) -> int:
    return value.days


@pytest.mark.parametrize(
    "runbook",
    [STUCK_OPERATION, SOLVE_FAILING, DEBOUNCE_TUNING, GOOGLE_TOKEN_EXPIRED],
    ids=lambda one: one.name,
)
def test_the_runbook_exists_and_states_a_trigger(runbook: Path) -> None:
    """Every runbook opens with what made the reader come here, per the deployment section."""
    assert "## Trigger" in read(runbook)


@pytest.mark.parametrize("runbook", [STUCK_OPERATION, SOLVE_FAILING], ids=lambda one: one.name)
def test_the_runbook_names_the_capability_that_survives(runbook: Path) -> None:
    """The same rule the in-product degradation notices follow: say what still works."""
    assert "still projected" in read(runbook)


class TestTheStuckOperationRunbook:
    def test_it_states_what_the_reaper_does(self) -> None:
        text = read(STUCK_OPERATION)

        assert "## What the reaper does" in text
        assert LEASE_EXPIRED in text

    def test_it_states_how_to_force_it(self) -> None:
        text = read(STUCK_OPERATION)

        assert "## How to force it" in text
        assert "OperationMaintenance" in text, "the sweep an operator runs has to be named"

    def test_it_quotes_the_lease_the_code_uses(self) -> None:
        assert f"**{minutes(LEASE)} minutes**" in read(STUCK_OPERATION)

    def test_it_quotes_the_sweep_interval_the_loop_uses(self) -> None:
        assert f"**every {minutes(MAINTENANCE_INTERVAL)} minutes**" in read(STUCK_OPERATION)

    def test_it_quotes_the_attempt_bound(self) -> None:
        assert f"**{MAX_ATTEMPTS} attempts**" in read(STUCK_OPERATION)

    def test_it_quotes_both_retention_windows(self) -> None:
        text = read(STUCK_OPERATION)

        assert f"**{days(FAILED_RETENTION)} days**" in text
        assert f"**{days(SUCCEEDED_RETENTION)} days**" in text

    def test_it_states_that_nothing_else_is_pruned(self) -> None:
        assert "prunes nothing else" in read(STUCK_OPERATION)


class TestTheSolveFailingRunbook:
    def test_it_names_the_snapshot_as_the_reproduction_mechanism(self) -> None:
        text = read(SOLVE_FAILING)

        assert "failed_input_snapshot" in text
        assert "load the snapshot and call the solver" in text

    def test_it_states_why_the_input_version_cannot_do_that_job(self) -> None:
        """A counter, not a snapshot: re-assembling yields current state rather than what failed."""
        text = read(SOLVE_FAILING)

        assert "`input_version` is a **counter**" in text
        assert "not the state that failed" in text

    def test_it_states_that_supersession_is_not_this_alert(self) -> None:
        """Presenting a displaced solve as a failure sends an operator diagnosing normal use."""
        assert "**Not an error.**" in read(SOLVE_FAILING)

    def test_it_quotes_the_retry_rules_the_code_uses(self) -> None:
        text = read(SOLVE_FAILING)

        assert f"| Attempts before a failure is terminal | {MAX_ATTEMPTS} |" in text
        assert f"| Backoff between attempts | {int(RETRY_BACKOFF.total_seconds())} seconds" in text

    def test_it_quotes_both_retention_windows(self) -> None:
        text = read(SOLVE_FAILING)

        assert f"{days(FAILED_RETENTION)} days" in text
        assert f"{days(SUCCEEDED_RETENTION)} days" in text

    def test_it_states_the_fallback_for_a_week_with_no_plan(self) -> None:
        """The horizon is never left with a hole: materialization's second permanent job."""
        assert "the horizon is never left with a hole" in read(SOLVE_FAILING)

    def test_it_does_not_claim_the_reproduction_runs_today(self) -> None:
        """The callout is the sentence a reader under pressure trusts, so it must not overclaim.

        It claimed the procedure was "complete" while its own "Still to be written" listed the first
        step. An operator following it reached a script that prints ``null`` with no explanation.
        """
        text = read(SOLVE_FAILING)

        assert "reproduction's FIRST step is unwritten" in text
        assert "nothing writes a snapshot yet" in text.lower()
        assert "reproduction procedure is complete" not in text

    def test_it_warns_where_the_null_snapshot_will_be_met(self) -> None:
        """Beside the script that prints it, not only in the callout at the top."""
        _before, _, after = read(SOLVE_FAILING).partition("### Read the snapshot")

        assert "expected rather than a lost snapshot" in after.split("###")[0]


class TestTheGoogleTokenExpiredRunbook:
    """The third runbook, and the one whose procedure is longest.

    Every identifier it quotes is crossed against the code that produces it: a notice id, an error
    code, a log event, a wire field, an environment variable, a column. A runbook that names a log
    line nobody emits sends an operator looking for evidence that does not exist.
    """

    def test_it_states_a_trigger_and_what_survives(self) -> None:
        text = read(GOOGLE_TOKEN_EXPIRED)

        assert "## Trigger" in text
        assert "## Surviving capability" in text
        assert "still read" in text, "the reader has to be told anchor ingest is unaffected"

    def test_it_answers_every_item_it_used_to_defer(self) -> None:
        """The stub listed five open items and a callout warning not to trust their absence."""
        text = read(GOOGLE_TOKEN_EXPIRED)

        assert "> **Stub.**" not in text
        assert "## Confirm that refresh is the failing step" in text
        assert "## Distinguish the three ways refreshing stops working" in text
        assert "## Tell a displaced token from a revoked one" in text
        assert "## Prove the write target is current after reconnecting" in text
        assert "## When it is not the token" in text

    def test_it_quotes_the_two_notice_identities_the_code_raises(self) -> None:
        text = read(GOOGLE_TOKEN_EXPIRED)

        assert f"`{WRITE_TARGET_EXPIRED}`" in text
        assert f"`{PROJECTION_STOPPED}`" in text

    def test_it_quotes_the_two_error_codes_the_code_sets(self) -> None:
        text = read(GOOGLE_TOKEN_EXPIRED)

        assert f"`{ProjectionRefused.code}`" in text
        assert f"`{ProjectionFailed.code}`" in text

    @pytest.mark.parametrize(
        "event",
        [
            "calendars.projection.completed",
            "calendars.projection.failed",
            "calendars.projection.skipped",
            "calendars.projection.tenant_failed",
            "google_account.connected",
        ],
    )
    def test_every_log_event_it_names_is_one_the_code_emits(
        self, event: str, source_root: Path
    ) -> None:
        assert f"`{event}`" in read(GOOGLE_TOKEN_EXPIRED)
        emitted = any(f'"{event}"' in path.read_text() for path in source_root.rglob("*.py"))
        assert emitted, f"the runbook names {event}, which nothing emits"

    def test_it_quotes_the_environment_variable_that_switches_writing_on(self) -> None:
        """Named in the message the product renders too, so the two cannot drift apart."""
        assert "`GOOGLE_PROJECTION_WRITES`" in read(GOOGLE_TOKEN_EXPIRED)
        assert "GOOGLE_PROJECTION_WRITES" in UNARMED.reason

    def test_it_quotes_the_credential_columns_that_exist(self) -> None:
        text = read(GOOGLE_TOKEN_EXPIRED)
        columns = {column.name for column in GoogleCredential.__table__.columns}

        for named in ("refresh_failing_since", "last_refresh_error", "connected_at"):
            assert named in text
            assert named in columns

    def test_it_quotes_the_sync_state_fields_the_wire_carries(self) -> None:
        text = read(GOOGLE_TOKEN_EXPIRED)
        fields = set(SyncStateResponse.model_json_schema(by_alias=True)["properties"])

        for named in ("lastSuccessAt", "lastAttemptAt", "lastError", "attempts"):
            assert f"`{named}`" in text
            assert named in fields

    def test_it_does_not_claim_an_alert_that_cannot_fire(self) -> None:
        """The stub said the critical alert fires. Its metric is exported by nothing at all.

        A runbook whose trigger names an alert that cannot fire tells an operator they will be told,
        which is exactly the silence that makes this failure dangerous.
        """
        text = read(GOOGLE_TOKEN_EXPIRED)

        assert "the alert cannot fire" in text
        assert REGISTRY.get_sample_value("syncr_write_target_token_age_seconds") is None

    def test_it_names_the_one_failure_that_raises_no_banner(self) -> None:
        """Every stated failure records itself on the target; a pass that raised did not.

        So the runbook has to say which line to look for and which counter counts it, or the reader
        concludes from a healthy product that nothing happened.
        """
        text = read(GOOGLE_TOKEN_EXPIRED)

        assert "the one case with no banner" in text
        assert TENANT_PROJECTION_FAILURES._name in text

    def test_it_states_the_deadline_the_code_enforces(self) -> None:
        """The figure an operator compares a recurring overrun against."""
        assert f"stopped after {WRITE_DEADLINE_SECONDS:.0f}s" in read(GOOGLE_TOKEN_EXPIRED)


class TestTheDebounceRunbook:
    """The window's own figures, and the three claims an operator has to be able to find.

    The threshold and the default are both quoted, and both are asserted against what produces
    them: a runbook telling an operator to raise a value it names wrongly is worse than one that
    names no value at all.
    """

    def test_it_quotes_the_default_window_the_code_ships(self) -> None:
        assert f"**{DEFAULT_SOLVE_DEBOUNCE_MS} ms**" in read(DEBOUNCE_TUNING)

    def test_it_names_the_environment_variable_that_changes_it(self) -> None:
        # The name is the field on EnvSettings upper-cased, which is how the settings base reads it.
        assert "SOLVE_DEBOUNCE_MS" in read(DEBOUNCE_TUNING)

    def test_it_names_both_instruments_the_ratio_is_read_from(self) -> None:
        body = read(DEBOUNCE_TUNING)

        assert "syncr_solve_superseded_ratio" in body
        assert "syncr_solve_total" in body

    def test_both_instruments_it_names_are_exported(self) -> None:
        """So the runbook cannot tell an operator to read a metric nothing publishes."""
        assert REGISTRY.get_sample_value("syncr_solve_superseded_ratio") is not None
        assert (
            REGISTRY.get_sample_value("syncr_solve_total", {"outcome": SUPERSEDED_STATUS})
            is not None
        )

    def test_it_says_the_window_is_fixed_rather_than_sliding(self) -> None:
        # The property the whole mechanism rests on, and the one an operator raising the value has
        # to understand: a longer window does not mean a user editing continuously waits longer.
        assert "does not extend it" in read(DEBOUNCE_TUNING)

    def test_it_says_a_high_ratio_is_not_an_error_rate(self) -> None:
        assert "not an error rate" in read(DEBOUNCE_TUNING)
