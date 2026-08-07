"""The alert-to-metric crossing, DERIVED in both directions, and the rules that govern the twelve.

A family with no rule and a rule with no family are the two halves of the same defect, and this
deployment has shipped it four times: a counter that incremented before its document existed, a
gauge that could not fire for a duty failing every pass, a critical alert on a metric no process
exported, and an SSE reconnect counter that stayed at zero through a killed backend.

So neither direction is a list anyone maintains:

- The EXPORTED set is read from the Prometheus registry, after importing every module whose source
  constructs a collector. Filesystem-driven, so a family added by a later ticket is in the crossing
  without this file being touched.
- The WATCHED set is read from the alert rules and the four dashboards as they are deployed.

What IS a list is :data:`UNWATCHED`, and every entry states why. A family that is watched by nothing
is legitimate only when someone has said so in writing, which is the difference between a decision
and an oversight.

Nothing here needs a running Prometheus, and nothing here needs a YAML library. The rule file's
shape is fixed and this repository owns it, so the reader below is a narrow parser over that shape.
What the files MEAN to Prometheus is checked by ``just monitoring-check``, which runs ``promtool``
and ``amtool`` over the same two files: a library here would add a dependency, not a guarantee.
"""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

import syncr_api
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# ---------------------------------------------------------------------------
# THE TWELVE, exactly as `18-observability.md` names them, with the severity each carries.
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
    "LearningJobFailed": "info",
}

DASHBOARDS: Final = ("product.json", "plan-pipeline.json", "calendar.json", "system.json")

# Families a rule reads that THIS application does not export, and what does. A rule over a family
# nothing produces cannot fire, so the allowance is a declaration rather than a silence: each entry
# names the producer, and a rule reading a name that is neither exported nor listed here fails.
EXTERNALLY_PRODUCED: Final[Mapping[str, str]] = {
    "syncr_backup_last_success_timestamp_seconds": (
        "Written by the nightly backup into the node exporter's textfile collector, because a "
        "script that has exited cannot be scraped. Ticket 58 owns the script; `BackupStale` reads "
        "this name with an `absent()` disjunct, so the alert fires on a deployment where no backup "
        "has ever run rather than staying silent until one does."
    ),
}

# Families that ARE drawn on a dashboard and deliberately carry no alert. Each states why, because a
# family an operator can see and cannot be paged about is a decision.
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

# Families no rule and no panel reads, and why each is legitimate. A family absent from BOTH sides
# of the crossing and absent from here fails the test, which is what makes this list the record of a
# decision rather than the record of an omission.
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
    "syncr_observability_tenant_failures_total": (
        "The state reading's own contained fault. Its consequence is that a gauge stops moving, "
        "and the alerts over those gauges use `absent()` and staleness, so the outage is visible "
        "through them. An alert on the observability layer failing to observe would be recursive."
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


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    """One alert rule as the deployed file declares it."""

    alert: str
    expr: str
    holds_for: str
    severity: str
    annotations: Mapping[str, str]


def deployments() -> Path:
    """The deployment configuration directory, resolved from this file rather than the cwd."""
    return Path(syncr_api.__file__).resolve().parents[4] / "deployments"


# The rule file is a sequence of blocks, each opened by `- alert: <Name>`. Every field this test
# reads is a `key: value` line inside one, and an `expr` may be a folded scalar spanning several.
_BLOCK = re.compile(r"^\s*- alert:\s*(?P<name>\w+)\s*$", re.MULTILINE)
_FIELD = re.compile(r"^\s*(?P<key>[a-z_]+):\s*(?P<value>.*)$", re.MULTILINE)


def alert_rules() -> list[Rule]:
    """Every rule the deployed file declares, in file order.

    Split on the block opener rather than parsed as YAML: the shape is fixed, this repository owns
    the file, and ``promtool`` is what confirms Prometheus can read it.
    """
    text = (deployments() / "prometheus" / "alerts.yml").read_text()
    openers = list(_BLOCK.finditer(text))
    bounds = [*(one.start() for one in openers), len(text)]
    return [
        _rule(opener.group("name"), text[opener.end() : bounds[position + 1]])
        for position, opener in enumerate(openers)
    ]


def _rule(name: str, body: str) -> Rule:
    expression, _, remainder = body.partition("labels:")
    _, _, annotated = remainder.partition("annotations:")
    return Rule(
        alert=name,
        expr=_folded(expression, key="expr"),
        holds_for=_stated(expression, key="for"),
        severity=_stated(remainder, key="severity"),
        annotations={
            found.group("key"): _folded(annotated, key=found.group("key"))
            for found in _FIELD.finditer(annotated)
            if not found.group("key").startswith("#")
        },
    )


def _stated(region: str, *, key: str) -> str:
    """One single-line field's value, or the empty string when the region does not carry it."""
    for found in _FIELD.finditer(region):
        if found.group("key") == key:
            return found.group("value").strip()
    return ""


def _folded(region: str, *, key: str) -> str:
    """One field's value including the continuation lines a folded scalar spans.

    A rule's expression and its annotations are written as ``>-`` blocks, so the value on the key's
    own line is a marker and the content is the more-indented lines under it.
    """
    lines = region.splitlines()
    for position, line in enumerate(lines):
        found = _FIELD.match(line)
        if found is None or found.group("key") != key:
            continue
        stated = found.group("value").strip()
        if stated and stated not in (">-", ">", "|", "|-"):
            return stated
        opened = len(line) - len(line.lstrip())
        continued = []
        for following in lines[position + 1 :]:
            if not following.strip():
                break
            if len(following) - len(following.lstrip()) <= opened:
                break
            continued.append(following.strip())
        return " ".join(continued)
    return ""


def panels(name: str) -> list[dict[str, Any]]:
    """One dashboard's panels. The JSON boundary is the one place an untyped shape is accepted."""
    parsed: dict[str, Any] = json.loads(
        (deployments() / "grafana" / "dashboards" / name).read_text()
    )
    return list(parsed["panels"])


def dashboard_text(name: str) -> str:
    """One dashboard's file as text, for the assertions about what a panel SAYS."""
    return (deployments() / "grafana" / "dashboards" / name).read_text()


# A metric name as it appears in a query, with the suffixes a histogram or a counter adds.
_FAMILY = re.compile(r"\bsyncr_[a-z0-9_]+")
_SUFFIXES = ("_bucket", "_count", "_sum", "_total")


def base_family(referenced: str) -> str:
    """The family a referenced series belongs to, with the client library's suffixes removed."""
    for suffix in _SUFFIXES:
        if referenced.endswith(suffix):
            return referenced.removesuffix(suffix)
    return referenced


def families_in(text: str) -> set[str]:
    """Every syncr family a block of query text reads."""
    return {base_family(found) for found in _FAMILY.findall(text)}


def panel_queries(name: str) -> Iterator[str]:
    for panel in panels(name):
        for target in panel.get("targets", ()):
            yield str(target.get("expr", ""))


def exported_families() -> set[str]:
    """Every family this application declares, read from the registry.

    Filesystem-driven rather than read from whatever the test run happened to import: a module is
    imported here exactly when its SOURCE constructs a collector, so a family declared by a module
    nothing else in the suite touches is still in the crossing.
    """
    root = Path(syncr_api.__file__).resolve().parent
    constructs = re.compile(r"\b(?:Counter|Gauge|Histogram|Summary)\(")
    for path in sorted(root.rglob("*.py")):
        if constructs.search(path.read_text()):
            importlib.import_module(
                "syncr_api." + str(path.relative_to(root).with_suffix("")).replace("/", ".")
            )
    # The learning job's six families live in another distribution and are scraped through the node
    # exporter's textfile collector, so they are part of the same crossing.
    importlib.import_module("syncr_learning.metrics")
    return {metric.name for metric in REGISTRY.collect() if metric.name.startswith("syncr_")}


def watched_families() -> set[str]:
    """Every family an alert rule or a dashboard panel reads."""
    return alerted_families() | drawn_families()


def alerted_families() -> set[str]:
    """Every family an alert rule reads."""
    return {family for rule in alert_rules() for family in families_in(rule.expr)}


def drawn_families() -> set[str]:
    """Every family a dashboard panel draws."""
    return {
        family
        for name in DASHBOARDS
        for query in panel_queries(name)
        for family in families_in(query)
    }


def named(name: str) -> Rule:
    """The one rule with this name. Raises if the file holds none or two."""
    (found,) = [one for one in alert_rules() if one.alert == name]
    return found


def declared(names: Mapping[str, str]) -> set[str]:
    """A declared list's keys, in the registry's own spelling.

    The lists above are written in the spec's spelling, which keeps a counter's ``_total``, and the
    client library reports a counter under its base name. Normalising here is what lets a reader of
    those lists recognise the family a query names.
    """
    return {base_family(one) for one in names}


class TestTheExtractionItself:
    """Positive controls. A crossing whose extraction returns nothing passes forever.

    Both sides of the crossing are set differences, so an extraction that silently found no families
    would make every assertion above trivially true. These four assert the extraction works, which
    is the only part of this file that can fail quietly.
    """

    def test_it_reads_a_family_through_every_suffix_the_client_library_adds(self) -> None:
        query = (
            "histogram_quantile(0.99, rate(syncr_probe_duration_seconds_bucket[5m])) "
            "+ increase(syncr_solve_total[1h]) "
            "+ rate(syncr_solve_empty_slots_sum[1h]) / rate(syncr_solve_empty_slots_count[1h])"
        )

        assert families_in(query) == {
            "syncr_probe_duration_seconds",
            "syncr_solve",
            "syncr_solve_empty_slots",
        }

    def test_a_family_no_process_exports_is_not_in_the_exported_set(self) -> None:
        """The synthetic input the containment assertions would otherwise never see."""
        assert families_in("increase(syncr_not_a_family_total[5m]) > 0") == {"syncr_not_a_family"}
        assert "syncr_not_a_family" not in exported_families()

    def test_the_filesystem_walk_finds_a_family_nothing_else_imports(self) -> None:
        """Read from the registry after walking the tree, not from whatever the suite imported.

        The learning families live in another distribution and the token gauge in a module only the
        worker's state duty touches, so both are absent from a registry built by imports alone.
        """
        exported = exported_families()

        assert "syncr_learning_run_duration_seconds" in exported
        assert "syncr_write_target_token_age_seconds" in exported
        assert len(exported) > 40

    def test_both_sides_of_the_crossing_are_non_empty(self) -> None:
        assert len(alerted_families()) > 5
        assert len(drawn_families()) > 20


class TestTheTwelve:
    def test_there_are_exactly_twelve_rules(self) -> None:
        """Twelve, and no thirteenth. Alert fatigue is the failure mode on a personal deployment."""
        assert len(alert_rules()) == len(SEVERITY_BY_ALERT)

    def test_the_names_are_section_eighteen_s_own(self) -> None:
        assert {rule.alert for rule in alert_rules()} == set(SEVERITY_BY_ALERT)

    @pytest.mark.parametrize(("name", "severity"), sorted(SEVERITY_BY_ALERT.items()))
    def test_each_carries_the_severity_it_was_given(self, name: str, severity: str) -> None:
        assert named(name).severity == severity

    def test_a_failed_solve_is_a_warning_and_a_missing_backup_is_critical(self) -> None:
        """The severity scheme in one assertion: a failed solve loses nothing, a backup all."""
        assert SEVERITY_BY_ALERT["SolveFailing"] == "warning"
        assert SEVERITY_BY_ALERT["BackupStale"] == "critical"

    @pytest.mark.parametrize("name", sorted(SEVERITY_BY_ALERT))
    def test_each_annotation_names_the_surviving_capability(self, name: str) -> None:
        """The same rule the in-product degradation notices follow.

        An operator woken at 03:00 needs to know what still works before they know what broke, and a
        summary alone never says that.
        """
        annotations = named(name).annotations

        assert annotations["surviving"].strip()
        assert annotations["summary"].strip()
        assert annotations["runbook"].strip()

    @pytest.mark.parametrize("name", sorted(SEVERITY_BY_ALERT))
    def test_each_rule_waits_before_it_fires(self, name: str) -> None:
        """No alert fires on a single sample. A transient is not a condition."""
        assert named(name).holds_for


class TestTheCrossing:
    """Both directions, derived, and each as an EXACT equality rather than a containment.

    A containment leaves one side free to grow unnoticed. Stated as equality, a family that gained a
    rule and kept its exemption fails, and so does a family that lost its rule and has none.
    """

    def test_every_family_a_rule_or_a_panel_reads_is_exported_or_declared_external(self) -> None:
        """A rule with no family cannot fire, which is the same silence as having no rule."""
        assert watched_families() <= exported_families() | declared(EXTERNALLY_PRODUCED)

    def test_every_exported_family_is_watched_or_declared_unwatched(self) -> None:
        """A family with no rule and no panel is legitimate only when someone said so in writing."""
        assert exported_families() - watched_families() == declared(UNWATCHED)

    def test_every_family_that_is_drawn_and_not_alerted_says_why(self) -> None:
        """The other half of the crossing: what an operator can see and cannot be paged about."""
        assert drawn_families() - alerted_families() == declared(NOT_ALERTED)

    def test_nothing_is_declared_unwatched_that_is_watched(self) -> None:
        """A stale exemption reads as a decision nobody has revisited."""
        assert declared(UNWATCHED) & watched_families() == set()

    def test_nothing_is_declared_unwatched_that_is_not_exported(self) -> None:
        """An exemption for a family that no longer exists is an exemption nobody reads."""
        assert declared(UNWATCHED) <= exported_families()

    def test_an_external_family_is_one_this_application_does_not_export(self) -> None:
        """Otherwise the allowance would hide a family that IS ours and stopped being exported."""
        assert declared(EXTERNALLY_PRODUCED) & exported_families() == set()

    @pytest.mark.parametrize("family", sorted({**UNWATCHED, **NOT_ALERTED, **EXTERNALLY_PRODUCED}))
    def test_each_declaration_states_a_reason(self, family: str) -> None:
        # Long enough to be a sentence rather than a word: "not needed" is not a reason.
        stated = {**UNWATCHED, **NOT_ALERTED, **EXTERNALLY_PRODUCED}[family]

        assert len(stated) > 80

    def test_every_section_eighteen_family_exists(self) -> None:
        """The spec's own tables, crossed against what the application actually declares.

        The four that ticket 30 and ticket 53 found missing are here by name, because each was a
        family a dashboard or an alert read and no process produced.
        """
        named_by_the_spec = {
            "syncr_http_request_duration_seconds",
            "syncr_http_requests_total",
            "syncr_http_errors_total",
            "syncr_probe_duration_seconds",
            "syncr_assembly_duration_seconds",
            "syncr_sse_connections",
            "syncr_db_pool_in_use",
            "syncr_db_query_duration_seconds",
            "syncr_solve_duration_seconds",
            "syncr_solve_total",
            "syncr_solve_iterations",
            "syncr_solve_blocks_placed",
            "syncr_solve_empty_slots",
            "syncr_materialize_total",
            "syncr_horizon_weeks_without_plan",
            "syncr_maintainer_tick_duration_seconds",
            "syncr_maintainer_verdict_transitions_total",
            "syncr_operations_non_terminal",
            "syncr_operation_queue_delay_seconds",
            "syncr_solve_superseded_ratio",
            "syncr_verdict_transitions_total",
            "syncr_calendar_sync_duration_seconds",
            "syncr_calendar_sync_total",
            "syncr_calendar_events_read",
            "syncr_calendar_events_rejected_total",
            "syncr_anchors_current",
            "syncr_source_staleness_seconds",
            "syncr_projection_duration_seconds",
            "syncr_projection_events",
            "syncr_write_target_token_age_seconds",
            "syncr_learning_run_duration_seconds",
            "syncr_learning_parameters_ready",
            "syncr_learning_parameters_collecting",
            "syncr_learning_samples",
            "syncr_learning_fit_rejected_total",
            "syncr_weight_set_version",
            "syncr_estimate_ape_median",
            "syncr_infeasibility_caught_early_ratio",
            "syncr_proposal_acceptance_ratio",
            "syncr_repins_per_week",
            "syncr_engagement_streak_weeks",
        }

        assert {base_family(one) for one in named_by_the_spec} <= exported_families()

    def test_every_family_the_spec_names_is_watched(self) -> None:
        """Exporting a family nothing reads is the other half of the same defect.

        Ticket 28 recorded five families in the plan pipeline with no alert and called it a standing
        rule rather than a per-ticket catch. Stated here, the spec's own inventory is the floor: a
        family section 18 names and nothing watches fails, whatever the exemption list says.
        """
        named_by_the_spec = {
            "syncr_http_request_duration_seconds",
            "syncr_http_requests_total",
            "syncr_http_errors_total",
            "syncr_probe_duration_seconds",
            "syncr_assembly_duration_seconds",
            "syncr_sse_connections",
            "syncr_db_pool_in_use",
            "syncr_db_query_duration_seconds",
            "syncr_solve_duration_seconds",
            "syncr_solve_total",
            "syncr_solve_iterations",
            "syncr_solve_blocks_placed",
            "syncr_solve_empty_slots",
            "syncr_materialize_total",
            "syncr_horizon_weeks_without_plan",
            "syncr_maintainer_tick_duration_seconds",
            "syncr_maintainer_verdict_transitions_total",
            "syncr_operations_non_terminal",
            "syncr_operation_queue_delay_seconds",
            "syncr_solve_superseded_ratio",
            "syncr_verdict_transitions_total",
            "syncr_calendar_sync_duration_seconds",
            "syncr_calendar_sync_total",
            "syncr_calendar_events_read",
            "syncr_calendar_events_rejected_total",
            "syncr_anchors_current",
            "syncr_source_staleness_seconds",
            "syncr_projection_duration_seconds",
            "syncr_projection_events",
            "syncr_write_target_token_age_seconds",
            "syncr_learning_run_duration_seconds",
            "syncr_estimate_ape_median",
            "syncr_infeasibility_caught_early_ratio",
            "syncr_proposal_acceptance_ratio",
            "syncr_repins_per_week",
            "syncr_engagement_streak_weeks",
        }

        assert {base_family(one) for one in named_by_the_spec} <= watched_families()


class TestTheRulesThatGovernTheRules:
    def test_no_alert_fires_on_a_foreign_deletion(self) -> None:
        """A superseded solve is normal and so is a foreign deletion: neither is actionable.

        A sustained foreign-deletion count is a PRODUCT signal that the user is still editing in
        their calendar client, which is a fact about fit rather than a fault to repair. It is drawn
        on the Calendar dashboard and paged about nowhere.
        """
        expressions = " ".join(rule.expr for rule in alert_rules())

        assert "foreign_deleted" not in expressions
        assert "foreign_deleted" in dashboard_text("calendar.json")

    def test_the_supersession_alert_reads_a_sustained_ratio_and_not_an_event(self) -> None:
        """A superseded solve is the expected outcome of editing quickly."""
        rule = named("SupersededRatioHigh")

        assert "rate(" in rule.expr
        assert "0.3" in rule.expr
        assert rule.holds_for == "24h"

    def test_the_projection_alert_inhibits_on_the_arming_state(self) -> None:
        """Two outcome values alone would trade a silent alert for an always-firing one.

        Writes are off in every deployment until a person has run the live Google suite, so every
        plan change produces a refusal recorded as a failure. The arming gauge is what separates
        'syncr cannot write' from 'syncr is not permitted to write'.
        """
        (rule,) = [one for one in alert_rules() if one.alert == "ProjectionFailing"]

        assert "syncr_projection_writes_enabled == 1" in rule.expr

    def test_the_probe_alert_is_labelled_by_the_request_caller(self) -> None:
        """The maintainer's roughly 288 background probes a day must neither mask nor trigger it."""
        rule = named("ProbeSlow")

        assert 'caller="request"' in rule.expr
        assert "syncr_probe_duration_seconds_bucket" in rule.expr
        assert "0.01" in rule.expr

    def test_the_assembly_alert_is_separate_and_reads_the_assembly(self) -> None:
        """THE ASSEMBLY, NOT THE PROBE, IS THE DOMINANT COST OF A PIN.

        `ProbeSlow` measures only the arithmetic that sits on top of the assembly, so without a
        separate alert a regression in the repository reads every live verdict depends on would be
        invisible to monitoring: the probe's own figure would not move at all.
        """
        rule = named("AssemblySlow")

        assert "syncr_assembly_duration_seconds_bucket" in rule.expr
        assert 'caller="request"' in rule.expr
        assert "0.15" in rule.expr
        assert rule.severity == "warning"

    @pytest.mark.parametrize(
        "name", ["BackupStale", "DatabaseUnreachable", "DiskFillingUp", "LearningJobFailed"]
    )
    def test_a_rule_over_a_family_that_may_not_exist_says_absent(self, name: str) -> None:
        """A threshold alone is SILENT while its series is missing, and missing is often worse.

        No backup has ever run. The exporter is down. The learning container has no timer yet. Each
        of those reads as healthy to a bare comparison, which is the alert inversion this ticket
        exists to end.
        """
        (rule,) = [one for one in alert_rules() if one.alert == name]

        assert "absent(" in rule.expr


class TestTheDashboards:
    def test_there_are_four_and_no_more(self) -> None:
        """A dashboard nobody reads is a maintenance cost. Four is the budget."""
        provisioned = sorted(
            path.name for path in (deployments() / "grafana" / "dashboards").glob("*.json")
        )

        assert provisioned == sorted(DASHBOARDS)

    @pytest.mark.parametrize("name", DASHBOARDS)
    def test_each_panel_names_its_datasource_by_the_provisioned_uid(self, name: str) -> None:
        """A dashboard whose datasource uid does not exist draws nothing and says nothing."""
        for panel in panels(name):
            assert panel["datasource"]["uid"] == "syncr-prometheus"

    def test_the_product_dashboard_trends_all_four_metrics(self) -> None:
        queries = " ".join(panel_queries("product.json"))

        assert families_in(queries) == {
            "syncr_estimate_ape_median",
            "syncr_infeasibility_caught_early_ratio",
            "syncr_proposal_acceptance_ratio",
            "syncr_repins_per_week",
            "syncr_engagement_streak_weeks",
        }

    def test_the_calendar_dashboard_draws_the_five_things_it_answers(self) -> None:
        drawn = families_in(" ".join(panel_queries("calendar.json")))

        assert (
            declared(
                {
                    "syncr_calendar_sync_total": "",
                    "syncr_source_staleness_seconds": "",
                    "syncr_calendar_events_read": "",
                    "syncr_calendar_events_rejected_total": "",
                    "syncr_write_target_token_age_seconds": "",
                    "syncr_projection_events": "",
                }
            )
            <= drawn
        )

    def test_the_system_dashboard_draws_memory_against_the_declared_limit(self) -> None:
        """Usage against the container's OWN bound, so it is visible before the kernel steps in."""
        queries = " ".join(panel_queries("system.json"))

        assert "container_spec_memory_limit_bytes" in queries
        assert "container_memory_working_set_bytes" in queries

    def test_the_maintainer_s_cost_is_stated_as_assemblies_and_probes(self) -> None:
        """Note 7: the maintainer performs roughly 288 ASSEMBLIES AND PROBES a day.

        The assembly is the cost. A panel that named only the probes would understate the dominant
        one by an order of magnitude, which is the correction ticket 43 made to the spec.
        """
        text = dashboard_text("system.json")

        assert "288 ASSEMBLIES AND PROBES" in text.upper()
        assert "THE ASSEMBLY IS THE COST" in text.upper()

    def test_the_product_dashboard_records_that_adherence_is_not_a_metric(self) -> None:
        """Optimizing it rewards under-planning, and the reason has to travel with the dashboard."""
        text = dashboard_text("product.json").lower()

        assert "adherence rate is deliberately absent" in text
        assert "under-planning" in text
