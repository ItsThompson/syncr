"""The figures the operation runbooks quote, crossed against the code that decides them.

A runbook is read once, under pressure, by someone deciding whether to intervene. One whose numbers
have drifted from the deployment is worse than none: it will be trusted, and it will be wrong. So
every figure these two quote is asserted against the constant that produces it, rather than against
a second copy of the number here.

The prose claims are asserted too, and each is one the ticket requires the runbook to make. They are
matched as substrings rather than by structure, because what has to survive is the STATEMENT: an
operator searching the file for "lease" has to find what the lease is.
"""

from __future__ import annotations

import importlib
import re
import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Final

import pytest

from syncr_api.calendars.config import CALENDAR_SOURCES_PREFIX, SYNC_INTERVAL
from syncr_api.calendars.google_config import WRITE_DEADLINE_SECONDS
from syncr_api.calendars.injection import UNARMED
from syncr_api.calendars.projection_errors import ProjectionFailed, ProjectionRefused
from syncr_api.calendars.projection_notices import PROJECTION_STOPPED
from syncr_api.calendars.projection_runner import TENANT_PROJECTION_FAILURES
from syncr_api.calendars.schemas import SyncStateResponse
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS
from syncr_api.google_account.config import (
    AUTHORIZATION_ENDPOINT,
    CALLBACK_ROUTE,
    CONNECT_PATH,
    CONNECTION_PATH,
    FORCE_CONSENT,
    OFFLINE_ACCESS,
    REQUESTED_SCOPES,
    RESPONSE_TYPE_CODE,
    TOKEN_ENDPOINT,
)
from syncr_api.google_account.models import GoogleCredential
from syncr_api.google_account.notices import WRITE_TARGET_EXPIRED
from syncr_api.horizon.config import MAINTAINER_INTERVAL
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
from tests.test_alert_rules import named as alert_named
from tests.test_google_live import (
    CLIENT_ID_VAR,
    CLIENT_SECRET_VAR,
    DEVELOPMENT_CALENDAR,
    HORIZON_DAYS,
    RECONCILED_DAY,
    REDIRECT_URI_VAR,
    REFRESH_TOKEN_VAR,
    SAFE_TITLE,
    WINDOW_LENGTH,
    WRITE_DAYS_AHEAD,
)

RUNBOOKS: Final = Path(__file__).resolve().parents[3] / "docs" / "runbooks"

STUCK_OPERATION = RUNBOOKS / "stuck-operation.md"
SOLVE_FAILING = RUNBOOKS / "solve-failing.md"
DEBOUNCE_TUNING = RUNBOOKS / "debounce-tuning.md"
GOOGLE_TOKEN_EXPIRED = RUNBOOKS / "google-token-expired.md"
GOOGLE_OAUTH_VERIFICATION = RUNBOOKS / "google-oauth-verification.md"
ENV_EXAMPLE = RUNBOOKS.parents[1] / ".env.example"
SOURCE_STALE = RUNBOOKS / "ics-feed-broken.md"
HORIZON_NOT_MAINTAINED = RUNBOOKS / "horizon-not-maintained.md"


def read(runbook: Path) -> str:
    assert runbook.is_file(), f"{runbook} does not exist"
    return runbook.read_text(encoding="utf-8")


def minutes(value: timedelta) -> int:
    return int(value.total_seconds() // 60)


def days(value: timedelta) -> int:
    return value.days


def hours(value: timedelta) -> int:
    return int(value.total_seconds() // 3600)


@pytest.mark.parametrize(
    "runbook",
    [
        STUCK_OPERATION,
        SOLVE_FAILING,
        DEBOUNCE_TUNING,
        GOOGLE_TOKEN_EXPIRED,
        GOOGLE_OAUTH_VERIFICATION,
        SOURCE_STALE,
        HORIZON_NOT_MAINTAINED,
    ],
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

    def test_it_claims_an_alert_that_can_now_fire(self) -> None:
        """Ticket 30 asserted the metric was ABSENT, because the alert could not fire without it.

        That assertion was written to fail the moment the gap closed, and that is what it did: the
        family exists, the worker's state duty sets it once a minute, and the runbook now says so.
        A runbook whose trigger names an alert that cannot fire tells an operator they will be told,
        which is exactly the silence that makes this failure dangerous.
        """
        text = read(GOOGLE_TOKEN_EXPIRED)
        # Imported for its registration: the family exists once the module that declares it is
        # loaded, and the worker loads it through the duty that sets the gauge.
        importlib.import_module("syncr_api.google_account.token_metrics")
        exported = {metric.name for metric in REGISTRY.collect()}

        assert "that metric is now exported" in text
        assert "the alert cannot fire" not in text
        assert "syncr_write_target_token_age_seconds" in exported

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

    def test_it_says_the_guarantee_is_per_window_rather_than_per_burst(self) -> None:
        # The two readings differ for sustained editing, which is exactly the case an operator reads
        # the ratio during: inside one window a burst costs one solve, and editing past the window
        # loses roughly one per solve-duration.
        assert "per window**, not per burst" in read(DEBOUNCE_TUNING)

    def test_it_says_which_of_the_three_figures_were_measured_here(self) -> None:
        # The window is a considered default rather than a fitted one, because the burst it is sized
        # for has no endpoint to produce it yet. A runbook that implied otherwise would have an
        # operator tuning against a figure nothing in this deployment has ever exercised.
        assert "not readings taken from this" in read(DEBOUNCE_TUNING)


def alert_waits(name: str) -> timedelta:
    """How long an alert rule waits before it fires, as the deployed file states it."""
    stated = alert_named(name).holds_for
    unit = stated[-1]
    value = int(stated[:-1])
    return {
        "s": timedelta(seconds=value),
        "m": timedelta(minutes=value),
        "h": timedelta(hours=value),
        "d": timedelta(days=value),
    }[unit]


class TestADutyCadenceAgainstTheAlertThatWatchesIt:
    """Two figures that must stay ordered, crossed here because nothing else crosses them.

    Each of these alerts reads a gauge a periodic duty publishes, so ONE MISSED PASS MUST NOT FIRE
    IT. That safety is a relationship between two constants in two different files, decided by
    neither: a reviewer found it holding only by coincidence. Raising a duty's interval past its
    alert's `for` window turns every ordinary pass into a page, and this is what fails when someone
    does.

    The re-inclusion case is what made it worth crossing. A source excluded and then re-included
    republishes its pre-exclusion staleness at once, so the reading is immediately over the
    threshold and stays there until the next poll succeeds. It is not a spurious page only because
    the poll interval is shorter than the wait.
    """

    def test_a_source_is_polled_more_often_than_its_alert_waits(self) -> None:
        assert alert_waits("SourceStale") > SYNC_INTERVAL, (
            f"sources are polled every {minutes(SYNC_INTERVAL)}m and SourceStale waits "
            f"{alert_named('SourceStale').holds_for}. A poll interval at or past the wait makes "
            "one missed poll a page, and makes a re-included source page immediately."
        )

    def test_the_horizon_is_maintained_more_often_than_its_alert_waits(self) -> None:
        assert alert_waits("HorizonNotMaintained") > MAINTAINER_INTERVAL, (
            f"the maintainer plans every {minutes(MAINTAINER_INTERVAL)}m and "
            f"HorizonNotMaintained waits {alert_named('HorizonNotMaintained').holds_for}. The "
            "gauge is legitimately non-zero for up to one pass whenever the horizon extends."
        )

    def test_the_source_runbook_quotes_both_figures_from_the_code(self) -> None:
        """So an operator reading it sees the relationship rather than one half of it."""
        text = read(SOURCE_STALE)

        assert f"**{minutes(SYNC_INTERVAL)} minutes**" in text
        assert f"**{minutes(alert_waits('SourceStale'))} minutes**" in text

    def test_the_horizon_runbook_quotes_both_figures_from_the_code(self) -> None:
        text = read(HORIZON_NOT_MAINTAINED)

        assert f"**{minutes(MAINTAINER_INTERVAL)} minutes**" in text
        assert f"**{hours(alert_waits('HorizonNotMaintained'))} hours**" in text


def the_live_marker() -> str:
    """The marker that keeps the live suite out of a default run, read from the config that does it.

    Found by its own description rather than by position, so declaring a third marker cannot
    silently move which one this resolves to.
    """
    manifest = Path(__file__).resolve().parents[1] / "pyproject.toml"
    options = tomllib.loads(manifest.read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    declared: list[str] = list(options["markers"])
    marked = dict(one.split(":", 1) for one in declared)
    found = [name for name, stated in marked.items() if "Google" in stated]
    assert len(found) == 1, f"exactly one declared marker should name Google, and {found} do"
    return found[0]


class TestTheLiveGoogleSuiteProcedure:
    """The one procedure in this repository a human runs against a real account.

    Every claim here gates that a referent RESOLVES: the environment variable the suite reads, the
    marker that excludes it, the calendar it writes to, the window it removes from, the scopes the
    grant has to carry. A wording can be anything; a referent either exists or it does not.

    It exists because the suite's own docstring said the runbook recorded where the refresh token
    lives, and no runbook mentioned the suite at all: the variable's name occurred once in the whole
    repository, in the test that reads it.
    """

    def test_it_names_every_value_the_suite_reads(self) -> None:
        """Four, and an absent one skips the whole suite, so a partial list wastes a consent."""
        text = read(GOOGLE_OAUTH_VERIFICATION)

        for named in (CLIENT_ID_VAR, CLIENT_SECRET_VAR, REDIRECT_URI_VAR, REFRESH_TOKEN_VAR):
            assert f"`{named}`" in text, f"the procedure does not name {named}"

    def test_it_names_the_command_that_runs_the_suite(self) -> None:
        """With the marker taken from the configuration that excludes it, not from a second copy.

        Bounded on the right by a space or an end of line, not by a space alone. A marker name is a
        prefix of every longer one, so `pytest -m google_livewire` satisfied an unbounded check; but
        requiring a trailing space reddened on the ticket's own settling command, which carries no
        flag after the marker.
        """
        marker = the_live_marker()

        assert re.search(
            rf"pytest -m {re.escape(marker)}(?:\s|$)", read(GOOGLE_OAUTH_VERIFICATION)
        ), f"the procedure names no runnable `pytest -m {marker}`"

    def test_it_names_the_calendar_every_write_lands_on(self) -> None:
        assert f"`{DEVELOPMENT_CALENDAR}`" in read(GOOGLE_OAUTH_VERIFICATION)

    def test_it_states_the_window_the_destructive_test_removes_from(self) -> None:
        """Both halves of it. An operator clearing the wrong two hours has cleared nothing.

        Anchored on the leading word, because a figure is a suffix of every longer figure: "12 hours
        long" contains "2 hours long", and "12 days ahead" contains "2 days ahead".
        """
        text = read(GOOGLE_OAUTH_VERIFICATION)

        assert f"is {hours(WINDOW_LENGTH)} hours long" in text
        assert f"sits {RECONCILED_DAY} days ahead of the moment" in text

    def test_it_states_the_whole_span_the_suite_writes_in(self) -> None:
        """Derived from the days the suite uses, so adding a probe day fails this, not the run."""
        span = f"between {min(WRITE_DAYS_AHEAD)} and {max(WRITE_DAYS_AHEAD)} days from now"

        assert span in read(GOOGLE_OAUTH_VERIFICATION)

    def test_it_states_the_horizon_the_read_of_every_calendar_covers(self) -> None:
        """The one test that touches the account's own calendars, so its reach is stated."""
        assert f"over the next {HORIZON_DAYS} days" in read(GOOGLE_OAUTH_VERIFICATION)

    def test_it_names_the_title_a_failed_run_leaves_behind(self) -> None:
        """So an event found on the calendar can be recognised rather than guessed at."""
        assert f"`{SAFE_TITLE}`" in read(GOOGLE_OAUTH_VERIFICATION)

    def test_it_quotes_every_scope_the_client_requests(self) -> None:
        """A grant narrower than the set fails the suite, so the set is what a consent carries.

        Anchored to a line of its own, which is how the verbatim block states them, because a scope
        string is a prefix of a narrower one: `calendar.events.owned.readonly` is a real scope this
        runbook discusses as a rejected alternative, and that drift silently downgrades the write
        grant while an unanchored check stays green.
        """
        text = read(GOOGLE_OAUTH_VERIFICATION)

        for scope in REQUESTED_SCOPES:
            assert f"\n{scope}\n" in text, f"{scope} is not quoted on a line of its own"

    def test_it_names_the_parameters_without_which_no_refresh_token_is_issued(self) -> None:
        """All three, because any one alone answers with an access token and nothing to store.

        Backticked on both sides, because each value is a prefix of a real longer one:
        `response_type=code` is a prefix of `response_type=code id_token`.
        """
        text = read(GOOGLE_OAUTH_VERIFICATION)

        assert f"`access_type={OFFLINE_ACCESS}`" in text
        assert f"`prompt={FORCE_CONSENT}`" in text
        assert f"`response_type={RESPONSE_TYPE_CODE}`" in text

    def test_it_names_both_endpoints_the_procedure_calls(self) -> None:
        """Backticked, because an endpoint is a prefix of a different real one: `/token` against
        `/tokeninfo`, and the authorization endpoint against any path below it.
        """
        text = read(GOOGLE_OAUTH_VERIFICATION)

        assert f"`{AUTHORIZATION_ENDPOINT}`" in text
        assert f"`{TOKEN_ENDPOINT}`" in text

    def test_every_callback_path_it_names_is_the_route_the_app_serves(self) -> None:
        """Per site, every site, and every character. Google matches a redirect URI exactly.

        The file names the path in three shapes, and a check against the file as a whole passes
        while any one drifts, so every occurrence is derived from the text rather than counted.

        **The trailing slash is the case worth naming.** This runbook says itself that a trailing
        slash is a usual cause of `redirect_uri_mismatch`, so it is exactly the drift the check
        exists for, and a pattern that stopped at the last word character read it as correct. The
        match therefore admits `/` and the comparison is against the whole token.

        The routes that legitimately share the prefix are **excluded by derivation** rather than by
        a pattern that happens not to reach them: `connect` and `connection` are real siblings, and
        a runbook naming either is not naming a broken callback. Deriving them from the app's own
        constants is what keeps a typo like `callbak` red while those two stay green.
        """
        below = CALLBACK_ROUTE.rsplit("/", 1)[0]
        siblings = {
            f"{CALENDAR_SOURCES_PREFIX}{CONNECT_PATH}",
            f"{CALENDAR_SOURCES_PREFIX}{CONNECTION_PATH}",
        }
        named = re.findall(rf"{re.escape(below)}/[A-Za-z0-9\-_/]*", read(GOOGLE_OAUTH_VERIFICATION))

        assert named, "the runbook names no path under the Google calendar-source prefix at all"
        for path in named:
            if path in siblings:
                continue
            assert path == CALLBACK_ROUTE, (
                f"{path} is not the callback route the app serves ({CALLBACK_ROUTE})"
            )

    def test_it_tells_the_redirect_uri_apart_from_the_browser_applications_origin(self) -> None:
        """Two settings, two different origins, and mistaking one for the other wastes a consent."""
        assert "is not `APP_BASE_URL`" in read(GOOGLE_OAUTH_VERIFICATION)
        # The assignment rather than the bare name: a name is a substring of every longer name, and
        # what has to survive is that the example file SETS this one.
        assert "\nAPP_BASE_URL=" in read(ENV_EXAMPLE), "the example file has to ship the setting"
