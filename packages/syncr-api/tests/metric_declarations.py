"""The declarations the alert-to-metric crossing is stated against, and the reason each one exists.

Data, kept apart from the assertions that read it. `test_alert_rules.py` was 810 lines and most of
it was these four tables, which left the crossing's own logic off the screen.

Nothing here is a list of what the deployment HAS. The crossing derives that, from the registry, the
rule file, the dashboards and the scrape configuration. What is here is the set of DECISIONS: a
family watched by nothing, a family drawn but deliberately not alerted, a family this application
does not produce, and which scrape job serves which member. Each is crossed against the derived sets
as an exact equality, so a decision that stopped being true fails rather than lingering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

# ---------------------------------------------------------------------------
# THE THIRTEEN, and the severity each carries.
#
# `18-observability.md` names twelve. THE THIRTEENTH IS `ClockDrifting`, and it is here because
# `19-nonfunctional.md`'s failure matrix names it as a row of its own, "clock skew on the host:
# alert on NTP drift", while section 18's table did not enumerate it. Ticket 58 resolved the two in
# favour of the rule existing: the frame and the now rule are computed against the host clock, so a
# drifting one leaves every plan correct and placed in the wrong day, and nothing else in the
# deployment would notice.
#
# `BackupStale` is critical while `SolveFailing` is a warning, and that pair is the whole severity
# scheme: A FAILED SOLVE LOSES NOTHING, because the previous plan is intact and still projected, and
# A MISSING BACKUP LOSES EVERYTHING.
# ---------------------------------------------------------------------------
SEVERITY_BY_ALERT: Final[Mapping[str, str]] = {
    "WriteTargetTokenExpiring": "critical",
    "ProjectionFailing": "critical",
    "BackupStale": "critical",
    "DatabaseUnreachable": "critical",
    "SolveFailing": "warning",
    "SourceStale": "warning",
    "SupersededRatioHigh": "warning",
    "ProbeSlow": "warning",
    "AssemblySlow": "warning",
    "HorizonNotMaintained": "warning",
    "DiskFillingUp": "warning",
    "ClockDrifting": "warning",
    "LearningJobFailed": "info",
}

DASHBOARDS: Final = ("product.json", "plan-pipeline.json", "calendar.json", "system.json")

# ---------------------------------------------------------------------------
# Family-shaped names that are NOT metric families.
#
# The literal scan reads every `syncr_`-prefixed string a source file holds, which is what lets it
# see a family constructed inside a function body: the name is on disk whether or not the function
# runs. Two names in this workspace have that exact shape and are not families, so they are declared
# here and crossed as an exact equality. A third noise name arriving without a row fails, and a row
# for a name that IS a family fails too.
# ---------------------------------------------------------------------------
NOT_A_FAMILY: Final[Mapping[str, str]] = {
    "syncr_events": (
        "The Postgres NOTIFY channel the event hub fans out from. A channel name, not a metric: it "
        "is passed to LISTEN and to NOTIFY, and it happens to share the application's own prefix."
    ),
    "syncr_session": (
        "The browser session cookie's name. Shares the prefix for the same reason the channel "
        "does, and is a wire identifier rather than anything the registry ever holds."
    ),
}

# ---------------------------------------------------------------------------
# WHICH SCRAPE JOB SERVES EACH MEMBER'S FAMILIES.
#
# A topology statement, and the one the `absent()` discipline is derived from. A family served by a
# job is covered by that job's liveness alert; a family whose member has NO job is produced by
# something that may never have run, so every rule reading one must say `absent()`.
#
# The api and the worker are two entrypoints of ONE member, so a family declared in `syncr_api` is
# recorded by whichever process reaches it and BOTH jobs must carry liveness. That is not a
# simplification: the plan pipeline is recorded in the worker and the request path in the api, and
# which of the two a given family belongs to is a property of the call site rather than of the
# declaration.
#
# Crossed against `prometheus.yml`'s own job list in both directions, so a job added without a
# member and a member naming no job both fail.
# ---------------------------------------------------------------------------
JOBS_BY_MEMBER: Final[Mapping[str, tuple[str, ...]]] = {
    "syncr_api": ("syncr-api", "syncr-worker"),
    "syncr_common": ("syncr-api", "syncr-worker"),
    "syncr_domain": ("syncr-api", "syncr-worker"),
    "syncr_solver": ("syncr-api", "syncr-worker"),
    "syncr_cli": ("syncr-api", "syncr-worker"),
    # The nightly one-shot has no service on the loop and no HTTP surface at all: a container that
    # has exited cannot be scraped, so it writes its exposition to a file the node exporter serves.
    # Its families are therefore absent until the timer has run at least once
    # (`deployments/systemd/syncr-learning.timer`).
    "syncr_learning": (),
}

# ---------------------------------------------------------------------------
# EVERY FAMILY `18-observability.md` NAMES, and whether the deployment must WATCH it.
#
# One table rather than two overlapping lists. An empty reason means the family is on the floor: it
# must be read by a rule or drawn on a panel, whatever any exemption says, which is what closes
# ticket 28's five orphans properly. A reason means the spec names the family for the product's own
# sake rather than for an operator's, and the same family must ALSO appear in `UNWATCHED` with its
# own reason, so escaping the floor takes two deliberate statements rather than one.
# ---------------------------------------------------------------------------
SPEC_FAMILIES: Final[Mapping[str, str]] = {
    "syncr_http_request_duration_seconds": "",
    "syncr_http_requests_total": "",
    "syncr_http_errors_total": "",
    "syncr_probe_duration_seconds": "",
    "syncr_assembly_duration_seconds": "",
    "syncr_sse_connections": "",
    "syncr_db_pool_in_use": "",
    "syncr_db_query_duration_seconds": "",
    "syncr_solve_duration_seconds": "",
    "syncr_solve_total": "",
    "syncr_solve_iterations": "",
    "syncr_solve_blocks_placed": "",
    "syncr_solve_empty_slots": "",
    "syncr_materialize_total": "",
    "syncr_horizon_weeks_without_plan": "",
    "syncr_maintainer_tick_duration_seconds": "",
    "syncr_maintainer_verdict_transitions_total": "",
    "syncr_operations_non_terminal": "",
    "syncr_operation_queue_delay_seconds": "",
    "syncr_solve_superseded_ratio": "",
    "syncr_verdict_transitions_total": "",
    "syncr_calendar_sync_duration_seconds": "",
    "syncr_calendar_sync_total": "",
    "syncr_calendar_events_read": "",
    "syncr_calendar_events_rejected_total": "",
    "syncr_anchors_current": "",
    "syncr_source_staleness_seconds": "",
    "syncr_projection_duration_seconds": "",
    "syncr_projection_events": "",
    "syncr_write_target_token_age_seconds": "",
    "syncr_learning_run_duration_seconds": "",
    "syncr_estimate_ape_median": "",
    "syncr_infeasibility_caught_early_ratio": "",
    "syncr_proposal_acceptance_ratio": "",
    "syncr_repins_per_week": "",
    "syncr_engagement_streak_weeks": "",
    "syncr_learning_parameters_ready": (
        "A progress figure for the user, rendered on the Learned screen. Section 18 lists it so "
        "the maturity gates are observable, not so an operator is paged about a young corpus."
    ),
    "syncr_learning_parameters_collecting": (
        "The complement of the family above, listed by section 18 and rendered on the Learned "
        "screen for the same reason: a parameter still collecting is the gate working."
    ),
    "syncr_learning_samples": (
        "Observations behind each parameter, which is what the Learned screen draws six progress "
        "bars from. An operator cannot make the user log more outcomes."
    ),
    "syncr_learning_fit_rejected_total": (
        "A refused fit is the ordinary outcome of a young corpus, which is why the family carries "
        "a reason label. The fault case is the job exiting non-zero, which IS alerted."
    ),
    "syncr_weight_set_version": (
        "Which artefact is in force. A gauge that answers 'which', not 'how healthy': an "
        "activation is a deliberate user act rather than an incident."
    ),
}

# ---------------------------------------------------------------------------
# Families a rule reads that THIS application does not export, and what does.
# ---------------------------------------------------------------------------
EXTERNALLY_PRODUCED: Final[Mapping[str, str]] = {
    "syncr_backup_last_success_timestamp_seconds": (
        "Written by the nightly backup into the node exporter's textfile collector, because a "
        "script that has exited cannot be scraped. `deployments/ops/dump.py` writes it, only on "
        "success and only as its last step; `BackupStale` reads this name with an `absent()` "
        "disjunct, so the alert fires on a deployment where no backup has ever run rather than "
        "staying silent until one does."
    ),
    "syncr_wal_archive_last_success_timestamp_seconds": (
        "Written by the WAL shipper, `deployments/ops/ship.py`, the same way and for the same "
        "reason. It is a SECOND producer of one guarantee: the nightly dump bounds data loss to a "
        "bit under a day and this bounds it to minutes, which is the recovery point section 19 "
        "states and the only thing that observes it. The shipper refuses to write it while "
        "`pg_stat_archiver` reports a pending failure, because an empty staging volume reads "
        "identically to a healthy one."
    ),
}

# ---------------------------------------------------------------------------
# Families that ARE drawn on a dashboard and deliberately carry no alert.
# ---------------------------------------------------------------------------
NOT_ALERTED: Final[Mapping[str, str]] = {
    "syncr_estimate_ape_median": (
        "A rising estimate error is the product working as designed on a user whose estimates "
        "got worse. Paging about it would be paging about the user."
    ),
    "syncr_infeasibility_caught_early_ratio": (
        "A product target measured over weeks, not an incident. A ratio that fell is a planning "
        "habit to discuss at the weekly session, and there is no operational repair."
    ),
    "syncr_proposal_acceptance_ratio": (
        "Falls when the solver's proposals stop fitting the user, which is a weights question the "
        "learning layer answers over weeks. Nothing an operator does tonight changes it."
    ),
    "syncr_repins_per_week": (
        "The strongest available signal that the objective weights are wrong, and a signal to read "
        "on a trend: one busy week of pinning is not a fault."
    ),
    "syncr_engagement_streak_weeks": (
        "The health canary, and explicitly NOT a success target. An alert would page an operator "
        "about the user's own week off."
    ),
    "syncr_projection_events": (
        "Carries the foreign-deletion count, which is a PRODUCT signal rather than a fault: a "
        "sustained count means the user is still editing in their calendar client."
    ),
    "syncr_anchors_current": (
        "How many commitments each source contributes. A count that changes is the user's calendar "
        "changing, which is the input the product exists to read."
    ),
    "syncr_solve_iterations": (
        "The shape of a solve rather than its health. An iteration count has no threshold that "
        "means anything on its own."
    ),
    "syncr_solve_blocks_placed": (
        "A week with fewer blocks is usually a lighter week. A count that fell for a bad reason "
        "shows up as empty slots with a stated reason, which is the panel beside it."
    ),
    "syncr_solve_empty_slots": (
        "A slot the solver could not fill for a stated reason is the plan explaining itself, and "
        "the reasons are ordinary: the week is full, or nothing eligible fits."
    ),
    "syncr_solve_duration_seconds": (
        "Budgeted at under two seconds and run in the worker, so a slow solve delays a proposal "
        "and breaks nothing. A solve that never finishes is `SolveFailing`."
    ),
    "syncr_solve_superseded_ratio": (
        "The cumulative reading over this process's whole lifetime. `SupersededRatioHigh` reads "
        "the WINDOWED ratio, because a month-old process averages away the burst."
    ),
    "syncr_operation_queue_delay_seconds": (
        "Measures the worker falling behind, which every other alert on this loop surfaces as its "
        "own symptom. An alert here would be a second page for the real condition."
    ),
    "syncr_operations_non_terminal": (
        "An operation stuck non-terminal is returned by the reaper within one maintenance cadence. "
        "What it costs is a delayed proposal, and the alert for that is `SolveFailing`."
    ),
    "syncr_operation_reaper_races_lost_total": (
        "A race the loser recorded, which means the winner did the work. Losing a race is the "
        "mechanism working rather than failing."
    ),
    "syncr_solve_claim_races_lost_total": (
        "Two workers reached one due solve and one claimed it. The single-flight invariant holding "
        "is not an incident."
    ),
    "syncr_operation_sweep_tenant_failures_total": (
        "A maintenance pass that raised. Its consequence is operations sitting non-terminal for "
        "one more cadence, and the sweep retries with no operator involvement."
    ),
    "syncr_calendar_tenant_poll_failures_total": (
        "A poll pass that raised, whose consequence is a source going unread. That consequence IS "
        "alerted, by `SourceStale`, which reads staleness rather than the attempt."
    ),
    "syncr_worker_runner_failures_total": (
        "The loop's per-duty failure counter. Every duty it counts has an alert on its CONSEQUENCE "
        "instead, which is the reading that matters."
    ),
    "syncr_materialize_total": (
        "A materialization caused by `solve_failed` is a week that fell back to a derived-only "
        "plan, which is already alerted as `SolveFailing`."
    ),
    "syncr_verdict_transitions_total": (
        "A transition is the product working: the week became impossible, or stopped being. "
        "Neither reading is an operational fault."
    ),
    "syncr_maintainer_verdict_transitions_total": (
        "Transitions nothing but the clock caused, which is the maintainer doing its job. "
        "`HorizonNotMaintained` covers the maintainer NOT doing it."
    ),
    "syncr_maintainer_tick_duration_seconds": (
        "How long one maintainer tick took, by duty. A slow tick delays the horizon, which is what "
        "`HorizonNotMaintained` is stated over: this is where to look after it fires."
    ),
    "syncr_sse_connections": (
        "How many browsers are watching. Zero is the normal state of a personal deployment nobody "
        "has open, so no threshold is meaningful in either direction."
    ),
    "syncr_sse_events_dropped_total": (
        "An event dropped for a slow consumer. The client reconnects and re-reads the resource, so "
        "the surface converges without an operator."
    ),
    "syncr_sse_listener_reconnects_total": (
        "The listener re-establishing its connection, which is the recovery working. A count that "
        "will not settle shows up as dropped events beside it."
    ),
    "syncr_http_requests_total": (
        "Traffic. There is one user, so neither a rise nor a fall is a condition: the latency and "
        "error families beside it carry every alertable reading."
    ),
    "syncr_http_request_duration_seconds": (
        "Route latency, drawn against section 19's budgets. The two routes whose latency is a "
        "stated promise, the probe and the assembly, have alerts of their own."
    ),
    "syncr_http_errors_total": (
        "A 4xx is usually the client's own request and a 5xx is visible through whichever "
        "subsystem raised it. An aggregate alert would fire on a browser probing a stale URL."
    ),
    "syncr_db_pool_in_use": (
        "A pool at its ceiling shows up as latency on every route above it, which is what an "
        "operator acts on. The gauge says WHY, so it is drawn rather than paged."
    ),
    "syncr_db_query_duration_seconds": (
        "Per-repository read latency, a diagnostic for the alerts above it: `AssemblySlow` fires "
        "and this panel says which read got slower."
    ),
    "syncr_calendar_sync_duration_seconds": (
        "Bounded by a publisher rather than by syncr, so no threshold here is syncr's to meet. A "
        "read that stopped coming back at all is `SourceStale`."
    ),
    "syncr_calendar_events_read": (
        "How much each source offered. A drop is the user's calendar emptying, which is a planning "
        "input rather than a fault."
    ),
    "syncr_calendar_events_rejected_total": (
        "A rejection is the PUBLISHER's malformed component in four of its five classes, so the "
        "repair belongs to whoever publishes the feed. The panel states the reason per class."
    ),
    "syncr_calendar_sync_total": (
        "Attempts by outcome. A failing attempt's consequence is staleness, which `SourceStale` "
        "reads directly: alerting on the attempt would fire on one network refusal."
    ),
}

# ---------------------------------------------------------------------------
# Families no rule and no panel reads, and why each is legitimate.
# ---------------------------------------------------------------------------
UNWATCHED: Final[Mapping[str, str]] = {
    "syncr_method_duration_seconds": (
        "The shared per-method decorator covers every decorated method in the application, so a "
        "panel over it would be a panel over everything and an alert would have no threshold that "
        "means anything. It is a diagnostic to query once a dashboard says where to look."
    ),
    "syncr_method_errors_total": (
        "The same decorator's error counter. Every failure it counts also surfaces as an HTTP "
        "error, a failed solve outcome, or a contained tenant fault, each of which IS watched: an "
        "alert here would be a second page for a condition already paged."
    ),
    "syncr_observability_product_failures_total": (
        "The product job's own contained fault. Product metrics answer a question about weeks, so "
        "a failed run is caught by the next hourly one: there is nothing an operator does in the "
        "meantime, and section 18 forbids an alert for a condition the user cannot act on."
    ),
    "syncr_learning_parameters_ready": (
        "A count of parameters past their maturity gate. It rises as the corpus grows and a low "
        "value means the user has not used the product for long enough, which is not a fault. The "
        "Learned screen renders it, which is where it belongs."
    ),
    "syncr_learning_parameters_collecting": (
        "The complement of the family above. A parameter below its threshold is one waiting for "
        "evidence, which is the gate working, and the Learned screen is where the user sees it."
    ),
    "syncr_learning_samples": (
        "Observations behind each parameter. A progress figure, rendered on the Learned screen "
        "where the audience is the user. An operator cannot make the user log more outcomes."
    ),
    "syncr_learning_fit_rejected_total": (
        "A refused fit is the ordinary outcome of a young corpus, which is why the family carries "
        "a reason label. `LearningJobFailed` covers the case that IS a fault, which is the job "
        "exiting non-zero; alerting on a refusal would alert on the gate working."
    ),
    "syncr_learning_edits_without_measurement": (
        "The corpus that predates the measurement difference. It only ever falls, nothing can be "
        "done to it, and it is exported so a weight gate held back by history is distinguishable "
        "from one held back by a quiet user."
    ),
    "syncr_weight_set_version": (
        "Which artefact is in force. A gauge that answers 'which', not 'how healthy': the Learned "
        "screen renders it and an activation is a deliberate user act, not an incident."
    ),
}

# ---------------------------------------------------------------------------
# MATCHERS THAT CANNOT MEAN WHAT THEY SAY, and what each one would take to remove.
#
# A matcher constraining a label its family does not declare does something other than what it reads
# as, and the operator decides which. Measured in the pinned Prometheus against an unlabelled
# counter: `=`, and a regex that cannot match the empty string, select NO series, so the term is
# silent; `!=`, `!~`, and a regex that CAN match the empty string select the WHOLE series, so the
# filter is a no-op. Both are defects and they are opposite ones, so the operator is part of the key
# and each reason states the consequence it actually has.
#
# That is the quiet half of a rule: the file reads as though the condition is covered,
# `promtool check config` accepts it, and the alert behaves nothing like the way it is written.
#
# NOT A DECISION, unlike every other table here. Each entry is a rule that is broken, recorded so it
# is visible to a reader of the declarations rather than only to a reader of the expression, and
# crossed as an exact equality so a new one fails and a repaired one fails too. Each states the
# change that would remove it.
#
# Keyed as `<alert>:<family>:<label><operator>`, which is the form the crossing derives.
# ---------------------------------------------------------------------------
MATCHERS_ON_AN_UNDECLARED_LABEL: Final[Mapping[str, str]] = {
    "LearningJobFailed:syncr_learning_run_duration_seconds:outcome=": (
        "The nightly run's duration histogram declares no labels at all, so this equality selects "
        "no series and the rule can only ever fire on its `absent()` half, which is a run that has "
        "never reported. A night that ran and failed reads healthy, which is the one condition the "
        "rule exists for. Removing this entry takes an `outcome` label on the histogram in "
        "`syncr-learning` and one observation per outcome, so it is a change to the job rather "
        "than to the rule: the five other label matchers in the file read families that declare "
        "theirs, so the shape is settled and this is the only family missing it."
    ),
}
