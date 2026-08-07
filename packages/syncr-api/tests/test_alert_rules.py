"""The alert-to-metric crossing, DERIVED in every direction, and the file that decides delivery.

A family with no rule and a rule with no family are two halves of the same defect, and this
deployment has shipped it five times: a counter that incremented before its document existed, a
gauge that could not fire for a duty failing every pass, a critical alert on a metric no process
exported, an SSE reconnect counter that stayed at zero through a killed backend, and an Alertmanager
inhibit rule that silenced every warning in the deployment.

So no direction is a list anyone maintains:

- **EXPORTED** is read from the Prometheus registry after importing every module of all six
  workspace members. Not after importing the modules whose SOURCE constructs a collector: a family
  declared through a helper defined elsewhere never registers under that rule, and one such family
  passed the whole crossing when a reviewer tried it.
- **WATCHED** is read from the alert rules and the four dashboards as they are deployed.
- **WHICH RULES MUST SAY `absent()`** is derived from the deployment topology: each family maps to
  the member that declares it, each member to the scrape jobs that serve it, and a family whose
  member has no job is produced by something that may never have run.
- **WHICH PROCESSES NEED A LIVENESS ALERT** is derived from `prometheus.yml`'s own job list, crossed
  against the `up{job=...}` matchers in the rules, in both directions.
- **DELIVERY** is read from `alertmanager.yml`. Every inhibit rule must name its source by
  `alertname`, because the shape that does not is the one that shipped: a blanket
  `severity=critical` suppressing `severity=warning`, scoped by a label every alert shares.

What IS declared, in `tests/metric_declarations.py`, is the set of DECISIONS, each with a written
reason and each crossed as an exact equality.

Nothing here needs a running Prometheus, and nothing here needs a YAML library. The two config
files' shape is fixed and this repository owns them, so the readers below are narrow parsers over
that shape.
What the files MEAN to Prometheus and Alertmanager is checked by `just monitoring-check`; what
Alertmanager DOES with a firing alert is checked by `deployments/bin/alertmanager-probe.sh`, because
that is the one thing `amtool` cannot judge.
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
from tests.metric_declarations import (
    DASHBOARDS,
    EXTERNALLY_PRODUCED,
    JOBS_BY_MEMBER,
    NOT_ALERTED,
    SEVERITY_BY_ALERT,
    SPEC_FAMILIES,
    UNWATCHED,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# The workspace members that can declare a metric family, and where each one's source lives.
MEMBER_ROOTS: Final[Mapping[str, str]] = {
    "syncr_common": "packages/syncr-common/src",
    "syncr_domain": "packages/syncr-domain/src",
    "syncr_solver": "packages/syncr-solver/src",
    "syncr_api": "packages/syncr-api/src",
    "syncr_learning": "packages/syncr-learning/src",
    "syncr_cli": "cli/src",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    """One alert rule as the deployed file declares it."""

    alert: str
    expr: str
    holds_for: str
    severity: str
    annotations: Mapping[str, str]


@dataclass(frozen=True, slots=True, kw_only=True)
class Inhibition:
    """One Alertmanager inhibit rule, as the matchers it was written with."""

    sources: tuple[str, ...]
    targets: tuple[str, ...]
    equal: tuple[str, ...]


def repo_root() -> Path:
    return Path(syncr_api.__file__).resolve().parents[4]


def deployments() -> Path:
    """The deployment configuration directory, resolved from this file rather than the cwd."""
    return repo_root() / "deployments"


# ---------------------------------------------------------------------------
# Reading the two configuration files
# ---------------------------------------------------------------------------

# The rule file is a sequence of blocks, each opened by `- alert: <Name>`. Every field this test
# reads is a `key: value` line inside one, and an `expr` may be a folded scalar spanning several.
_BLOCK = re.compile(r"^\s*- alert:\s*(?P<name>\w+)\s*$", re.MULTILINE)
_FIELD = re.compile(r"^\s*(?P<key>[a-z_]+):\s*(?P<value>.*)$", re.MULTILINE)
# `- alertname = "X"` and `- alertname =~ "X|Y"`, as an inhibit rule's matchers are written.
_MATCHER = re.compile(r'^\s*-\s*(?P<label>[a-z_]+)\s*(?:=~|=)\s*"?(?P<value>[^"\n]*)"?\s*$')


def alert_rules() -> list[Rule]:
    """Every rule the deployed file declares, in file order."""
    text = (deployments() / "prometheus" / "alerts.yml").read_text()
    openers = list(_BLOCK.finditer(text))
    bounds = [*(one.start() for one in openers), len(text)]
    return [
        _rule(opener.group("name"), text[opener.end() : bounds[position + 1]])
        for position, opener in enumerate(openers)
    ]


def named(name: str) -> Rule:
    """The one rule with this name. Raises if the file holds none or two."""
    (found,) = [one for one in alert_rules() if one.alert == name]
    return found


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
    """One field's value including the continuation lines a folded scalar spans."""
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


def inhibitions() -> list[Inhibition]:
    """Every inhibit rule the Alertmanager configuration declares.

    Read at all, which is the point: the previous version of this file never opened
    `alertmanager.yml`, and the defect that shipped lived there and nowhere else.
    """
    text = (deployments() / "alertmanager" / "alertmanager.yml").read_text()
    _, _, region = text.partition("inhibit_rules:")
    region, _, _ = region.partition("\nreceivers:")
    return [_inhibition(block) for block in _inhibit_blocks(region)]


def _inhibit_blocks(region: str) -> Iterator[str]:
    """Each `- source_matchers:` block of the inhibit-rules region."""
    opener = re.compile(r"^\s*-\s*source_matchers:\s*$", re.MULTILINE)
    openers = list(opener.finditer(region))
    bounds = [*(one.start() for one in openers), len(region)]
    for position, found in enumerate(openers):
        yield region[found.start() : bounds[position + 1]]


def _inhibition(block: str) -> Inhibition:
    sources: list[str] = []
    targets: list[str] = []
    section = "source"
    for line in block.splitlines():
        if "target_matchers:" in line:
            section = "target"
            continue
        if "equal:" in line:
            section = "equal"
            continue
        found = _MATCHER.match(line)
        if found is None or section == "equal":
            continue
        (sources if section == "source" else targets).append(
            f"{found.group('label')}={found.group('value')}"
        )
    stated = _stated(block, key="equal")
    return Inhibition(
        sources=tuple(sources),
        targets=tuple(targets),
        equal=tuple(re.findall(r'"([^"]+)"', stated)),
    )


def scrape_jobs() -> set[str]:
    """Every job name `prometheus.yml` declares."""
    text = (deployments() / "prometheus" / "prometheus.yml").read_text()
    return set(re.findall(r"^\s*-\s*job_name:\s*(\S+)\s*$", text, re.MULTILINE))


# ---------------------------------------------------------------------------
# Reading the dashboards
# ---------------------------------------------------------------------------


def panels(name: str) -> list[dict[str, Any]]:
    """One dashboard's panels. The JSON boundary is the one place an untyped shape is accepted."""
    parsed: dict[str, Any] = json.loads(
        (deployments() / "grafana" / "dashboards" / name).read_text()
    )
    return list(parsed["panels"])


def dashboard_text(name: str) -> str:
    """One dashboard's file as text, for the assertions about what a panel SAYS."""
    return (deployments() / "grafana" / "dashboards" / name).read_text()


def panel_queries(name: str) -> Iterator[str]:
    for panel in panels(name):
        for target in panel.get("targets", ()):
            yield str(target.get("expr", ""))


# ---------------------------------------------------------------------------
# The two derived sets, and the topology they are crossed against
# ---------------------------------------------------------------------------

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


def exported_families() -> set[str]:
    """Every family this workspace declares, read from the registry.

    EVERY module of all six members is imported, not only the modules whose own source constructs a
    collector. A family declared through a helper defined elsewhere, or created lazily inside a
    function body, never registers under the narrower rule, so both set differences below would step
    over it: a reviewer shipped one such family past the entire crossing.
    """
    root = repo_root()
    for package, source in MEMBER_ROOTS.items():
        tree = root / source / package
        for path in sorted(tree.rglob("*.py")):
            module = package + "".join(f".{part}" for part in path.relative_to(tree).parts)
            importlib.import_module(module.removesuffix(".py").removesuffix(".__init__"))
    return {metric.name for metric in REGISTRY.collect() if metric.name.startswith("syncr_")}


def declaring_member(family: str) -> str | None:
    """Which member's source names this family, or ``None`` when no member does.

    Read from the source rather than from the collector, because a collector knows nothing about
    which distribution built it and the `absent()` requirement is stated per member.
    """
    root = repo_root()
    for package, source in MEMBER_ROOTS.items():
        tree = root / source / package
        for path in tree.rglob("*.py"):
            if f'"{family}' in path.read_text():
                return package
    return None


def families_with_no_job() -> set[str]:
    """Families whose declaring member is served by no scrape job.

    Produced by something that may never have run, so a rule reading one is silent unless it says
    `absent()`. Derived from the topology rather than listed, so a member that loses its service is
    covered without this file being touched.
    """
    return {
        family
        for family in exported_families()
        if (member := declaring_member(family)) is not None and not JOBS_BY_MEMBER[member]
    }


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


def watched_families() -> set[str]:
    """Every family an alert rule or a dashboard panel reads."""
    return alerted_families() | drawn_families()


def declared(names: Mapping[str, str]) -> set[str]:
    """A declared list's keys, in the registry's own spelling.

    The tables are written in the spec's spelling, which keeps a counter's ``_total``, and the
    client library reports a counter under its base name.
    """
    return {base_family(one) for one in names}


def liveness_jobs() -> set[str]:
    """Every job an alert rule reads the liveness of."""
    return set(re.findall(r'up\{job="([^"]+)"\}', " ".join(rule.expr for rule in alert_rules())))


class TestTheExtractionItself:
    """Positive controls. A crossing whose extraction returns nothing passes forever."""

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

    def test_the_walk_reaches_every_member_rather_than_the_api_tree(self) -> None:
        """A family in a member the api does not import must still be in the crossing.

        The learning families live in another distribution and the token gauge in a module only the
        worker's state duty touches. The solver's five reach the registry only because the api
        imports them transitively, which is the coupling this walk removes.
        """
        exported = exported_families()

        assert "syncr_learning_run_duration_seconds" in exported
        assert "syncr_write_target_token_age_seconds" in exported
        assert "syncr_method_duration_seconds" in exported
        assert "syncr_solve_iterations" in exported
        assert len(exported) > 40

    def test_it_attributes_each_family_to_the_member_that_declares_it(self) -> None:
        """The `absent()` requirement is derived from this, so a wrong attribution weakens it."""
        assert declaring_member("syncr_learning_run_duration_seconds") == "syncr_learning"
        assert declaring_member("syncr_method_duration_seconds") == "syncr_common"
        assert declaring_member("syncr_solve_iterations") == "syncr_solver"
        assert declaring_member("syncr_write_target_token_age_seconds") == "syncr_api"
        assert declaring_member("syncr_not_a_family") is None

    def test_both_sides_of_the_crossing_are_non_empty(self) -> None:
        assert len(alerted_families()) > 5
        assert len(drawn_families()) > 20

    def test_it_reads_the_inhibit_rules_and_the_scrape_jobs(self) -> None:
        """Both were unread until a defect shipped in one of them."""
        assert len(inhibitions()) >= 1
        assert scrape_jobs() >= {"syncr-api", "syncr-worker", "node", "cadvisor", "postgres"}


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


class TestDelivery:
    """`alertmanager.yml`, which decides whether a firing rule reaches anyone.

    Unread by this suite until a blanket inhibit rule silenced every warning in the deployment. The
    rule was syntactically perfect, so `amtool check-config` accepted it, and the effect was only
    visible by posting alerts to a real Alertmanager.
    """

    def test_no_inhibit_rule_matches_on_severity_alone(self) -> None:
        """The shape that shipped, forbidden by construction.

        `severity = critical` suppressing `severity = warning`, scoped with `equal: ["deployment"]`.
        `deployment` is an `external_labels` entry, so it is identical on all twelve rules: the rule
        read 'any firing critical suppresses every firing warning'. `BackupStale` fires
        unconditionally until ticket 58 writes its metric, so ten minutes after the stack first
        started, none of the seven warnings was deliverable.
        """
        for rule in inhibitions():
            assert any(matcher.startswith("alertname=") for matcher in rule.sources), (
                f"an inhibit rule sourced on {rule.sources} suppresses by class rather than by "
                "cause. Name the alert whose firing makes the targets redundant."
            )

    def test_every_alert_an_inhibit_rule_names_is_one_of_the_twelve(self) -> None:
        """A rule naming an alert that does not exist is dead, and a typo reads as one."""
        for rule in inhibitions():
            for matcher in (*rule.sources, *rule.targets):
                label, _, value = matcher.partition("=")
                if label != "alertname":
                    continue
                assert set(value.split("|")) <= set(SEVERITY_BY_ALERT), matcher

    def test_no_inhibit_rule_is_scoped_only_by_a_label_every_alert_shares(self) -> None:
        """`equal:` narrows nothing when the label it names comes from `external_labels`.

        It is legitimate BESIDE an alertname matcher, which is what actually narrows the rule, and
        it is what makes the rule a no-op if a second deployment ever shares a channel.
        """
        external = set(
            re.findall(
                r"^\s{4}(\w+):",
                (deployments() / "prometheus" / "prometheus.yml")
                .read_text()
                .partition("external_labels:")[2]
                .partition("\n\n")[0],
                re.MULTILINE,
            )
        )

        assert external, "prometheus.yml declares no external labels, so this guard reads nothing"
        for rule in inhibitions():
            assert not set(rule.equal) - external or any(
                matcher.startswith("alertname=") for matcher in rule.sources
            )


class TestLiveness:
    """Every process that exports a family must have an alert that fires when it stops.

    The ticket's own headline finding was a whole process whose registry nothing scraped. The
    equivalent silence is a process nothing watches: every plan-pipeline, calendar and token family
    is recorded in the worker, so a dead worker leaves a frozen gauge reading healthy and an absent
    counter with no increase. Derived from the scrape configuration, so a fifth process is visible.
    """

    def test_every_scrape_job_that_serves_a_family_has_a_liveness_alert(self) -> None:
        served = {job for jobs in JOBS_BY_MEMBER.values() for job in jobs}

        assert served <= liveness_jobs(), (
            f"{sorted(served - liveness_jobs())} export a metric family and no rule reads "
            "up{job=...} for them, so a stopped process leaves every rule over its families silent"
        )

    def test_every_liveness_matcher_names_a_job_the_scrape_configuration_declares(self) -> None:
        """The other direction: a matcher naming no job is a term that is always absent."""
        assert liveness_jobs() <= scrape_jobs()

    def test_every_member_names_jobs_the_scrape_configuration_declares(self) -> None:
        declared_jobs = {job for jobs in JOBS_BY_MEMBER.values() for job in jobs}

        assert declared_jobs <= scrape_jobs()

    def test_every_member_that_declares_a_family_is_in_the_topology(self) -> None:
        """A member added to the workspace without a row here would escape the whole guard."""
        declaring = {
            member
            for family in exported_families()
            if (member := declaring_member(family)) is not None
        }

        assert declaring <= set(JOBS_BY_MEMBER)

    def test_the_liveness_alert_is_critical(self) -> None:
        """Every rule over every worker-sourced family depends on it, so it is not a warning."""
        assert named("DatabaseUnreachable").severity == "critical"


class TestTheAbsentDiscipline:
    """Which rules must say `absent()`, derived rather than listed.

    A rule stated only as a threshold is silent while its series is missing, and a missing series is
    usually the more serious condition. The previous version of this guard was a four-name
    `parametrize`, which by construction could not see a fifth rule that needed the disjunct.
    """

    def test_every_rule_over_a_family_that_may_never_have_been_produced_says_absent(self) -> None:
        unproduced = families_with_no_job() | declared(EXTERNALLY_PRODUCED)

        for rule in alert_rules():
            if families_in(rule.expr) & unproduced:
                assert "absent(" in rule.expr, (
                    f"{rule.alert} reads {sorted(families_in(rule.expr) & unproduced)}, which "
                    "nothing in this deployment runs yet, so a threshold alone is silent"
                )

    def test_the_derivation_finds_the_families_it_is_stated_over(self) -> None:
        """The positive control: an empty `unproduced` set would make the rule above vacuous."""
        unproduced = families_with_no_job() | declared(EXTERNALLY_PRODUCED)

        assert "syncr_learning_run_duration_seconds" in unproduced
        assert "syncr_backup_last_success_timestamp_seconds" in unproduced
        # And a family the worker exports is NOT in it: the worker has a job, so its liveness alert
        # covers it and every rule over it need not carry the disjunct.
        assert "syncr_horizon_weeks_without_plan" not in unproduced

    def test_every_rule_over_an_exporter_family_says_absent(self) -> None:
        """An exporter that is down reads as plenty of disk and a healthy database."""
        for name in ("DiskFillingUp", "DatabaseUnreachable"):
            assert "absent(" in named(name).expr


class TestTheCrossing:
    """Both directions, derived, and each as an EXACT equality rather than a containment."""

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


class TestTheSpecInventoryIsAFloor:
    """Section 18's own tables, which no exemption can absorb.

    One constant rather than two overlapping lists. An empty reason puts the family on the floor; a
    reason lets it off, and the same family must then appear in `UNWATCHED` with its own. Escaping
    the floor therefore takes two deliberate statements in two places.
    """

    def test_every_family_the_spec_names_exists(self) -> None:
        assert {base_family(one) for one in SPEC_FAMILIES} <= exported_families()

    def test_every_family_the_spec_names_is_watched_unless_it_says_why_not(self) -> None:
        """Ticket 28's five orphans closed as a FLOOR rather than as a set of exemptions."""
        on_the_floor = {base_family(one) for one, reason in SPEC_FAMILIES.items() if not reason}

        assert on_the_floor <= watched_families()

    def test_a_spec_family_let_off_the_floor_is_also_declared_unwatched(self) -> None:
        """Two statements, in two places, or the family stays on the floor."""
        let_off = {base_family(one) for one, reason in SPEC_FAMILIES.items() if reason}

        assert let_off <= declared(UNWATCHED)

    @pytest.mark.parametrize(
        "family", sorted(one for one, reason in SPEC_FAMILIES.items() if reason)
    )
    def test_each_family_let_off_the_floor_states_a_reason(self, family: str) -> None:
        assert len(SPEC_FAMILIES[family]) > 80


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
        assert "syncr_projection_writes_enabled == 1" in named("ProjectionFailing").expr

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
