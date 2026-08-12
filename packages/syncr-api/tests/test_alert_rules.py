"""The alert-to-metric crossing, DERIVED in every direction, and the file that decides delivery.

A family with no rule and a rule with no family are two halves of the same defect, and this
deployment has shipped it repeatedly: a counter that incremented before its document existed, a
gauge that could not fire for a duty failing every pass, a critical alert on a metric no process
exported, an SSE reconnect counter that stayed at zero through a killed backend, and an Alertmanager
inhibit rule that silenced every warning in the deployment.

So no direction is a list anyone maintains:

- **EXPORTED** is read from the Prometheus registry after importing every module of all six
  workspace members. That covers a family declared through a helper defined elsewhere. It does NOT
  cover a family constructed inside a function body, because
  importing a module does not run one, so a SECOND reading is crossed against it: every
  family-shaped string literal on disk must be in the registry. A literal that is not is either a
  family a process can export and this crossing cannot see, or a name that was never a family, and
  the second is a short declared list with a written reason per entry.
- **WATCHED** is read from the alert rules and the four dashboards as they are deployed.
- **WHICH RULES MUST SAY `absent()`** is derived from the deployment topology: each family maps to
  the member that declares it, each member to the scrape jobs that serve it, and a family whose
  member has no job is produced by something that may never have run.
- **WHICH PROCESSES NEED A LIVENESS ALERT** is derived from `prometheus.yml`'s own job list: every
  job named for one of our processes must be read by an `up{job=...}` matcher, and every matcher
  must name a declared job. Read from the scrape configuration rather than from the member map,
  because the map is hand-maintained and a sixth job added without a row in it would pass.
- **DELIVERY** is read from `alertmanager.yml`. Every inhibit rule must name BOTH its source and its
  targets by `alertname`, because constraining the source alone left the shipped defect one edit
  away: `alertname="BackupStale"` targeting `severity="warning"` suppressed all seven warnings in a
  real Alertmanager while 131 tests and `amtool` passed. The reader opens `*_matchers:` blocks only,
  so the legacy `source_match:` map form is forbidden outright AND the rule count is crossed against
  the region's own list entries: a rule this file cannot open is a rule it cannot guard, and
  Alertmanager honours it regardless.

What IS declared, in `tests/metric_declarations.py`, is the set of DECISIONS, each with a written
reason and each crossed as an exact equality.

Nothing here needs a running Prometheus, and nothing here needs a YAML library. The two config
files' shape is fixed and this repository owns them, so the readers below are narrow parsers over
that shape.
What the files MEAN to Prometheus and Alertmanager is checked by `just monitoring-check`; what
Alertmanager DOES with a firing alert is checked by `deployments/bin/alertmanager-probe.py`, because
that is the one thing `amtool` cannot judge.
"""

from __future__ import annotations

import ast
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
    MATCHERS_ON_AN_UNDECLARED_LABEL,
    NOT_A_FAMILY,
    NOT_ALERTED,
    SEVERITY_BY_ALERT,
    SPEC_FAMILIES,
    UNWATCHED,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


# The workspace members that can declare a metric family, and where each one's source lives.
#
# DERIVED FROM `[tool.uv.workspace] members`, which is the list the build itself trusts, because the
# hand-maintained version was the last hinge in this file: a seventh member added without a row in
# it escaped the registry walk, the literal scan and both set differences at once. Every member
# keeps its importable package under exactly one `src/<package>` directory, which is the layout `uv`
# requires of a member and the only assumption made here.
def member_roots() -> Mapping[str, str]:
    """Every workspace member's import package, mapped to the source root that holds it."""
    root = repo_root()
    text = (root / "pyproject.toml").read_text()
    _, _, region = text.partition("[tool.uv.workspace]")
    listed, _, _ = region.partition("]")
    found: dict[str, str] = {}
    for member in re.findall(r'"([^"]+)"', listed):
        (package,) = sorted((root / member / "src").glob("*/__init__.py"))
        found[package.parent.name] = f"{member}/src"
    return found


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    """One alert rule as the deployed file declares it."""

    alert: str
    expr: str
    holds_for: str
    severity: str
    annotations: Mapping[str, str]


@dataclass(frozen=True, slots=True, kw_only=True)
class Comparison:
    """One threshold comparison inside a rule's expression, with the term it is stated over.

    A rule fires on an operator, a number and the range the term reads over, so a control that
    asserts the number alone passes when the operator flips or the window moves. All four are read
    together here for that reason.
    """

    families: frozenset[str]
    window: str
    operator: str
    threshold: float


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

    Read at all, which is the point: the crossing above says nothing about whether a firing rule
    reaches anyone, and the defect that shipped lived in `alertmanager.yml` and nowhere else.

    This reads the `*_matchers:` spelling ONLY, which is why
    :meth:`TestDelivery.test_no_inhibit_rule_uses_the_legacy_matcher_syntax` forbids the other one,
    and :meth:`TestDelivery.test_this_file_s_reader_sees_every_rule_alertmanager_will_load` counts
    the list entries independently of any spelling. Alertmanager still honours the pre-0.22
    `source_match:` map form, so a rule written that way was loaded, suppressed all seven warnings,
    and was invisible to this function.
    """
    return [_inhibition(block) for block in _inhibit_blocks(inhibit_region())]


def inhibit_region() -> str:
    """The inhibit-rules region of `alertmanager.yml`, as text."""
    text = (deployments() / "alertmanager" / "alertmanager.yml").read_text()
    _, _, region = text.partition("inhibit_rules:")
    region, _, _ = region.partition("\nreceivers:")
    return region


def inhibit_entries(region: str) -> int:
    """How many list entries the inhibit-rules region holds, whatever spelling each one uses.

    A YAML sequence entry opens with `- ` at the sequence's own indentation, and a matcher is a
    nested sequence indented further, so the outermost `- ` depth in the region IS the rule level.
    Counting there reads the file the way Alertmanager's loader does, by structure rather than by
    the key that follows, so a rule written in ANY accepted spelling is counted. It is the figure
    :func:`inhibitions` must agree with, and `amtool check-config` reports the same number.
    """
    openers = [
        len(line) - len(line.lstrip())
        for line in region.splitlines()
        if re.match(r"^\s*-\s+\S", line)
    ]
    if not openers:
        return 0
    return openers.count(min(openers))


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


# Our own processes' jobs are named for the application; an exporter's job is named for what it
# exports. That prefix is the whole distinction the liveness floor needs, and reading it off
# `prometheus.yml` is what makes a SIXTH PROCESS visible without any map being edited.
OUR_JOB_PREFIX: Final = "syncr-"

# The most alerts one cause can plausibly make redundant, which is what caps an inhibit rule's
# target list. Four is what this deployment's largest rule names: a process that is gone is the
# cause of four duties that stopped. Deliberately NOT derived from the twelve, because half the
# deployment was the previous cap and six of twelve is six of the seven warnings.
MOST_ALERTS_ONE_CAUSE_MAKES_REDUNDANT: Final = 4


def our_scrape_jobs() -> set[str]:
    """Every scrape job that is one of this application's own processes.

    Derived from the scrape configuration rather than from :data:`JOBS_BY_MEMBER`, because that map
    is hand-maintained: a sixth job added without a row in it would otherwise pass the whole suite.
    The exporters are correctly out of scope, each covered by an `absent()` term rather than by a
    liveness matcher.
    """
    return {job for job in scrape_jobs() if job.startswith(OUR_JOB_PREFIX)}


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


# A threshold comparison, and the range selector a term reads over. An instant vector carries none.
_COMPARISON = re.compile(r"(?P<operator>==|!=|>=|<=|>|<)\s*(?P<threshold>-?\d+(?:\.\d+)?)")
_WINDOW = re.compile(r"\[(?P<window>\d+[smhdwy])\]")


def comparisons(expr: str) -> list[Comparison]:
    """Every threshold comparison an expression states, in the order it states them.

    Each comparison is paired with the text since the previous one, which is the term being
    compared: a rule disjoins several terms and each carries its own families and its own window, so
    reading the numbers alone cannot say which term any of them bounds. A disjunct that states no
    comparison of its own, such as an `absent()` term, is absorbed into the term that follows it.
    """
    read: list[Comparison] = []
    opened = 0
    for found in _COMPARISON.finditer(expr):
        term = expr[opened : found.start()]
        opened = found.end()
        # The last range in the term. Every rule here bounds one range per comparison, and a ratio
        # of two ranges would report only the divisor's, so read `windows` below before relying on
        # this field for an expression that divides one window by a different one.
        windows = _WINDOW.findall(term)
        read.append(
            Comparison(
                families=frozenset(families_in(term)),
                window=windows[-1] if windows else "",
                operator=found.group("operator"),
                threshold=float(found.group("threshold")),
            )
        )
    return read


def comparison_on(rule: Rule, family: str) -> Comparison:
    """The one comparison this rule states over ``family``. Raises if it states none or two.

    The failure names both the rule and the family, because the caller that needs this most is the
    integration crossing over the token age, which has no parametrized test id to say what it was
    looking for when a rule stops stating the family it is supposed to read.
    """
    found = [one for one in comparisons(rule.expr) if family in one.families]
    if len(found) != 1:
        raise ValueError(
            f"{rule.alert} states {len(found)} comparisons over {family}, wanted exactly one"
        )
    return found[0]


def exported_families() -> set[str]:
    """Every family this workspace declares, read from the registry.

    EVERY module of all six members is imported, not only the modules whose own source constructs a
    collector. A family declared through a helper defined elsewhere never registers under the
    narrower rule, so both set differences below would step over it: one such family has been
    shipped past the entire crossing, twice, from two different members.

    Importing a module does not execute a function body, so this alone cannot see a family built
    lazily inside one. :func:`family_literals` is the second reading that does.
    """
    root = repo_root()
    for package, source in member_roots().items():
        tree = root / source / package
        for path in sorted(tree.rglob("*.py")):
            module = package + "".join(f".{part}" for part in path.relative_to(tree).parts)
            importlib.import_module(module.removesuffix(".py").removesuffix(".__init__"))
    return {metric.name for metric in REGISTRY.collect() if metric.name.startswith("syncr_")}


# A string a source file could be naming a metric family with: the prefix, and nothing a family name
# cannot contain. A dotted or colon-bearing name is a module path or a service identifier, excluded
# by shape rather than by a list.
_FAMILY_SHAPED = re.compile(r"^syncr_[a-z0-9_]+$")

# What the client library calls a collector. A family's name is such a call's first positional
# argument.
_COLLECTORS: Final = ("Counter", "Gauge", "Histogram", "Summary", "Info", "Enum")
_CLIENT_LIBRARY: Final = "prometheus_client"


def member_sources() -> Iterator[tuple[str, Path]]:
    """Every Python file of every workspace member, with the package it belongs to."""
    root = repo_root()
    for package, source in member_roots().items():
        tree = root / source / package
        for path in sorted(tree.rglob("*.py")):
            yield package, path


def family_literals() -> set[str]:
    """Every family-shaped string literal in all six members' sources, base-normalised.

    The reading that sees a family a process can export and an import cannot register: a collector
    constructed inside a function body has its NAME on disk whether or not anything calls the
    function. Crossed against the registry as an exact equality, so such a family fails rather than
    being stepped over by both set differences.

    Every literal, not only a call's first argument: two of this deployment's own families are
    passed by module constant rather than inline, and a rule reading only call arguments missed
    both.

    WHAT THIS READING CANNOT SEE ON ITS OWN is a name that is never written whole:
    `Gauge(f"{_PREFIX}_assembled", ...)` inside a function body exports a family no literal here
    matches. :func:`collector_names_are_plain_literals` is what makes that shape a failure instead
    of a hole, by requiring the name to BE a literal at every construction site.
    """
    found: set[str] = set()
    for _, path in member_sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _FAMILY_SHAPED.match(node.value)
            ):
                found.add(base_family(node.value))
    return found


def collector_names_are_plain_literals() -> list[str]:
    """Every collector construction whose name argument is not a plain string constant.

    The closing half of the literal reading. A family assembled from parts is exported by a running
    process and invisible to a scan for whole names, so the fix is to forbid the assembly rather
    than to widen the scan: a name built from a prefix constant is unreadable off the page by a
    person too. A module-level constant IS accepted, because its value is a literal one
    `ast.Constant` away and :func:`family_literals` already sees it.

    WHICH `Counter` IS THE CLIENT LIBRARY'S IS RESOLVED PER FILE, from that file's own imports,
    rather than by matching the bare name. `collections.Counter` is called in two members for
    tallying, and a reading that keyed on the name alone reported both as unnamed families. A
    hand-written exclusion list would have hidden the next such collision instead of resolving it.
    """
    offenders: list[str] = []
    for _, path in member_sources():
        tree = ast.parse(path.read_text())
        local = _client_library_names(tree)
        if not local:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            called = node.func
            name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
            if name not in local:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                continue
            if isinstance(first, ast.Name):  # a module constant, whose value is a literal on disk
                continue
            offenders.append(f"{path.name}:{node.lineno} {name}(...)")
    return offenders


def _client_library_names(tree: ast.Module) -> set[str]:
    """The names this module can construct a collector with, as it imported them."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _CLIENT_LIBRARY:
            found |= {
                (alias.asname or alias.name) for alias in node.names if alias.name in _COLLECTORS
            }
        if isinstance(node, ast.Import) and any(
            alias.name == _CLIENT_LIBRARY for alias in node.names
        ):
            found |= set(_COLLECTORS)  # reached as `prometheus_client.Gauge(...)`
    return found


def declaring_member(family: str) -> str | None:
    """Which member's source names this family, or ``None`` when no member does.

    Read from the source rather than from the collector, because a collector knows nothing about
    which distribution built it and the `absent()` requirement is stated per member.

    Matched on the family's own name as a whole word, so ``syncr_solve`` cannot be attributed by a
    substring of ``syncr_solve_total``: the two live in different members, and an attribution that
    flipped between them would silently change which rules must carry `absent()`.
    """
    root = repo_root()
    named = re.compile(rf'"{re.escape(family)}(?:_total)?"')
    for package, source in member_roots().items():
        tree = root / source / package
        for path in tree.rglob("*.py"):
            if named.search(path.read_text()):
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


# A series selector a rule reads, with whatever it constrains inside the braces. The space before
# the brace is optional in PromQL and Prometheus accepts either, so a reading that required the
# tight spelling would miss a real selector AND the control written to close that hole, because both
# read this one pattern.
_SELECTOR = re.compile(r"(?P<family>syncr_[a-z0-9_]+)\s*\{(?P<matchers>[^}]*)\}")
_SELECTOR_LABEL = re.compile(r"(?P<label>[a-z_]+)\s*(?P<operator>=~|!~|!=|=)")

# Labels no collector declares and every series may still carry: two the scrape attaches, one the
# client library adds to a histogram, and one this deployment sets as an external label. A matcher
# on any of them is about where a series came from rather than about how it was recorded.
_NOT_DECLARED_BY_A_COLLECTOR: Final = frozenset({"deployment", "instance", "job", "le"})

# What a matcher on a label the family does not declare actually DOES, by operator, measured in the
# pinned Prometheus against an unlabelled counter. An absent label reads as the empty string, so an
# equality against a non-empty value matches nothing while a negation matches everything: the two
# failures are opposites, and a recorded reason that states the wrong one is worse than one that
# states none. A regex is conditional because it decides on whether its own pattern accepts the
# empty string.
_CONSEQUENCE_OF: Final[Mapping[str, str]] = {
    "=": "selects no series",
    "=~": "selects no series unless its pattern matches the empty string",
    "!=": "selects every series",
    "!~": "selects every series",
}

# One declared key's matcher half, so the label and the operator are read from the key rather than
# trusted. A key this cannot parse is malformed and fails.
_KEYED_MATCHER = re.compile(r"(?P<label>[a-z_]+)(?P<operator>=~|!~|!=|=)")


def declared_labelnames() -> Mapping[str, frozenset[str]]:
    """Every family's own label set, read from the construction that declares it.

    Read from the source rather than from the registry, because the registry cannot answer this: a
    labelled collector with no child yet reports NO SAMPLES, so nothing in a collected metric names
    the labels it would carry. The labels are on the page, one keyword away from the name.

    Resolved per file from that file's own imports, for the reason
    :func:`collector_names_are_plain_literals` states. A ``labelnames`` this cannot read as literal
    strings FAILS here rather than being reported as no labels, which would turn every matcher over
    that family into an undeclared one.
    """
    found: dict[str, frozenset[str]] = {}
    for _, path in member_sources():
        tree = ast.parse(path.read_text())
        local = _client_library_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            called = node.func
            name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
            if name not in local:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            found[base_family(first.value)] = _labelnames_of(node, at=f"{path.name}:{node.lineno}")
    assert found, "no collector construction was read, so every matcher below would look broken"
    return found


def _labelnames_of(node: ast.Call, *, at: str) -> frozenset[str]:
    """The ``labelnames`` one collector construction declares, or the empty set when it declares
    none."""
    stated = next(
        (one.value for one in node.keywords if one.arg == "labelnames"),
        None,
    )
    if stated is None:
        return frozenset()
    assert isinstance(stated, ast.Tuple | ast.List), f"{at} states labelnames this cannot read"
    names = [
        one.value
        for one in stated.elts
        if isinstance(one, ast.Constant) and isinstance(one.value, str)
    ]
    assert len(names) == len(stated.elts), f"{at} states a labelname that is not a string literal"
    return frozenset(names)


def matchers_on_an_undeclared_label() -> set[str]:
    """Every ``<alert>:<family>:<label><operator>`` a rule constrains that its family does not have.

    A matcher on a label the family never declares CANNOT MEAN WHAT IT SAYS, and which way it fails
    depends on the operator, measured in the pinned Prometheus against an unlabelled counter: ``=``
    and a regex that cannot match the empty string select nothing, so the term is silent; ``!=``,
    ``!~`` and a regex that can match the empty string select the WHOLE series, so the filter is a
    no-op. Both are defects and they are opposite ones, which is why the operator is carried in the
    key rather than dropped: an entry's reason has to state the consequence it actually has.

    Derived from both ends: the rules as deployed, and the label sets the collectors declare.
    """
    labels = declared_labelnames()
    return {
        f"{rule.alert}:{family}:{found.group('label')}{found.group('operator')}"
        for rule in alert_rules()
        for selector in _SELECTOR.finditer(rule.expr)
        if (family := base_family(selector.group("family"))) in labels
        for found in _SELECTOR_LABEL.finditer(selector.group("matchers"))
        if found.group("label") not in labels[family] | _NOT_DECLARED_BY_A_COLLECTOR
    }


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

    def test_it_reads_each_threshold_with_the_operator_and_window_its_own_term_states(self) -> None:
        """The positive control for the comparison reader, on the shape a real rule has.

        Three terms, two windows, three operators and a number that is not a threshold at all: a
        reader that took the first number after a family would report `0.99` as the bound on the
        histogram and would attribute the arming state's `1` to whichever family it found first.
        """
        expr = (
            '(increase(syncr_projection_duration_seconds_count{outcome="failed"}[15m]) > 0 '
            "and on() syncr_projection_writes_enabled == 1) "
            "or histogram_quantile(0.99, rate(syncr_probe_duration_seconds_bucket[30m])) >= 0.01"
        )

        assert comparisons(expr) == [
            Comparison(
                families=frozenset({"syncr_projection_duration_seconds"}),
                window="15m",
                operator=">",
                threshold=0.0,
            ),
            Comparison(
                families=frozenset({"syncr_projection_writes_enabled"}),
                window="",
                operator="==",
                threshold=1.0,
            ),
            Comparison(
                families=frozenset({"syncr_probe_duration_seconds"}),
                window="30m",
                operator=">=",
                threshold=0.01,
            ),
        ]

    def test_a_term_a_rule_does_not_state_raises_and_names_what_it_looked_for(self) -> None:
        """A lookup that answered for a family the rule never mentions would pass on any rule.

        The message is asserted, not only the exception: the caller this protects is the crossing
        over the token age, and a bare unpacking error there names neither the rule that stopped
        stating the family nor the family it stopped stating.
        """
        with pytest.raises(
            ValueError,
            match=r"WriteTargetTokenExpiring states 0 comparisons over "
            r"syncr_source_staleness_seconds",
        ):
            comparison_on(named("WriteTargetTokenExpiring"), "syncr_source_staleness_seconds")

    def test_a_family_two_terms_bound_raises_rather_than_answering_for_one_of_them(self) -> None:
        """The other half of the contract, on a shape no rule states today.

        A rule that bounded one family from both sides would make "the comparison over this family"
        ambiguous, and answering with either one silently would pin half a condition. No deployed
        rule does this, so the input is built here rather than read from the file.
        """
        both_sides = Rule(
            alert="Synthetic",
            expr=(
                "max(syncr_source_staleness_seconds) > 86400 "
                "or min(syncr_source_staleness_seconds) < 60"
            ),
            holds_for="5m",
            severity="warning",
            annotations={},
        )

        assert len(comparisons(both_sides.expr)) == 2
        with pytest.raises(ValueError, match=r"Synthetic states 2 comparisons over"):
            comparison_on(both_sides, "syncr_source_staleness_seconds")

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

    def test_a_family_is_not_attributed_by_a_prefix_of_a_longer_one(self) -> None:
        """`syncr_solve` and `syncr_solve_iterations` live in DIFFERENT members.

        A substring match attributed the counter to whichever member the walk reached first, and the
        two carry the same job set today, so the wrong answer was invisible. It would stop being
        invisible the moment one member's job set changed, and the `absent()` requirement is derived
        from this answer.
        """
        assert declaring_member("syncr_solve") == "syncr_api"
        assert declaring_member("syncr_solve_iterations") == "syncr_solver"

    def test_both_sides_of_the_crossing_are_non_empty(self) -> None:
        assert len(alerted_families()) > 5
        assert len(drawn_families()) > 20

    def test_it_reads_the_inhibit_rules_and_the_scrape_jobs(self) -> None:
        """Both were unread until a defect shipped in one of them."""
        assert len(inhibitions()) >= 1
        assert scrape_jobs() >= {"syncr-api", "syncr-worker", "node", "cadvisor", "postgres"}

    def test_the_member_roots_are_the_workspace_s_own_members(self) -> None:
        """Derived from `[tool.uv.workspace] members`, which is the list the build already trusts.

        The last hand-maintained hinge in this file. A seventh member added without a row in the old
        map escaped the registry walk, the literal scan and both set differences at once, and only a
        person reading the map would notice. This asserts the derivation found all six and
        resolved each to a real source tree, so an empty or partial read cannot satisfy the sets it
        feeds.
        """
        roots = member_roots()

        assert set(roots) == {
            "syncr_common",
            "syncr_domain",
            "syncr_solver",
            "syncr_api",
            "syncr_learning",
            "syncr_cli",
        }
        assert roots["syncr_cli"] == "cli/src", "the one member that is not under packages/"
        for package, source in roots.items():
            assert (repo_root() / source / package / "__init__.py").is_file()

    def test_the_entry_count_sees_a_rule_the_block_reader_cannot_open(self) -> None:
        """The positive control for the count equality, and the escape it was built for.

        Without this, an entry counter that always returned `len(inhibitions())` would satisfy the
        equality forever. The legacy map form below is what a real Alertmanager loaded and honoured
        while this file's block reader saw nothing, so the counter must see two where the reader
        sees one.
        """
        legacy = (
            '\n  - source_matchers:\n      - alertname = "A"\n    target_matchers:\n'
            '      - alertname = "B"\n'
            "  - source_match:\n      alertname: WriteTargetTokenExpiring\n"
            "    target_match:\n      severity: warning\n"
        )

        assert inhibit_entries(legacy) == 2
        assert len(list(_inhibit_blocks(legacy))) == 1

    def test_every_collector_in_the_workspace_names_its_family_with_a_literal(self) -> None:
        """The closing half of the literal reading, and the shape it could not see.

        `Gauge(f"{_PREFIX}_assembled", ...)` inside a function body is exported by a running process
        and matched by no whole-name literal on disk, so the crossing stepped over it: measured, a
        plain interpreter that calls such a function exports the family while this suite passed. The
        fix is to forbid the assembly rather than widen the scan, because a name built from parts is
        unreadable off the page by a person too.

        The reading resolves which `Counter` is the client library's from each file's own imports:
        `collections.Counter` is called in two members and a name-only match reported both.
        """
        assert collector_names_are_plain_literals() == []


class TestTheThirteen:
    def test_there_are_exactly_thirteen_rules(self) -> None:
        """The rule file and the severity table hold the same number. Alert fatigue is the failure
        mode on a personal deployment, so neither may grow a rule the other does not carry.

        `ClockDrifting` is the one that watches the host clock rather than the product, and nothing
        else in the deployment would notice a drift; the reasoning is beside the rule and beside
        `SEVERITY_BY_ALERT`.
        """
        assert len(alert_rules()) == len(SEVERITY_BY_ALERT)

    def test_the_names_are_the_two_sections_own(self) -> None:
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
    def test_the_runbook_each_alert_names_is_a_file_that_exists(self, name: str) -> None:
        """A pointer that does not resolve is worse than no pointer.

        The assertion above asserted the string was non-empty, and a reader concluded a runbook was
        present: EIGHT of them pointed at files that did not exist, and one had a note recommended
        for it that nobody noticed had never been written. The defect class is in the guard rather
        than in the code: the set the assertion can see is not the set its name claims to bound.

        Resolved from the repository root, because that is what the annotation's path is relative to
        and what an operator reading the alert will type.
        """
        stated = named(name).annotations["runbook"]

        assert (repo_root() / stated).is_file(), (
            f"{name} points at {stated}, which does not exist. An operator following it at 03:00 "
            "finds nothing, which is the failure this deployment's whole alerting surface is for."
        )

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
        """The shape that shipped, and the shape it becomes in one edit, both forbidden.

        `severity = critical` suppressing `severity = warning`, scoped with `equal: ["deployment"]`.
        `deployment` is an `external_labels` entry, so it is identical on EVERY rule: the rule
        read 'any firing critical suppresses every firing warning'. `BackupStale` fired
        unconditionally while nothing wrote its metric, so ten minutes after the stack first
        started, none of the seven warnings was deliverable.

        BOTH SIDES ARE CONSTRAINED, because constraining the source alone left the same defect one
        edit away: `alertname = "BackupStale"` targeting `severity = "warning"` names its source by
        alertname, uses one of the twelve, and suppressed all seven warnings in a real Alertmanager
        while 131 tests and `amtool` passed. A class is not a cause on either side of the arrow.
        """
        for rule in inhibitions():
            assert any(matcher.startswith("alertname=") for matcher in rule.sources), (
                f"an inhibit rule sourced on {rule.sources} suppresses by class rather than by "
                "cause. Name the alert whose firing makes the targets redundant."
            )
            assert any(matcher.startswith("alertname=") for matcher in rule.targets), (
                f"an inhibit rule targeting {rule.targets} suppresses a CLASS rather than the "
                "named alerts one cause makes redundant. Name them, or the rule silences whatever "
                "else ever carries that label."
            )

    def test_no_inhibit_rule_uses_the_legacy_matcher_syntax(self) -> None:
        """THE PARSER ABOVE READS `*_matchers:`. ALERTMANAGER ALSO HONOURS THE OLDER MAP FORM.

        The third distinct route back to the shipped defect, and the one that walked past every
        instrument here. `source_match:` with a mapping under it is pre-0.22 syntax, still loaded by
        v0.28.0, still accepted by `amtool`, and INVISIBLE to :func:`_inhibit_blocks`. Written as
        `source_match: {alertname: WriteTargetTokenExpiring}` targeting `target_match:
        {severity: warning}`, it passed the whole suite, passed `amtool` with three rules while this
        file's reader saw two, exited the probe at 0 because the probe never posts that source, and
        suppressed ALL SEVEN warnings in a real Alertmanager.

        It is not an exotic spelling: it is what every pre-0.22 example shows, so it is the form a
        future editor is most likely to paste. One supported spelling, and the guards above then
        cover everything Alertmanager will honour.
        """
        text = (deployments() / "alertmanager" / "alertmanager.yml").read_text()

        for legacy in ("source_match:", "target_match:", "source_match_re:", "target_match_re:"):
            assert legacy not in text, (
                f"{legacy} is honoured by Alertmanager and invisible to this file's reader, so a "
                "rule written with it escapes every guard here. Use `source_matchers:` and "
                "`target_matchers:`."
            )

    def test_this_file_s_reader_sees_every_rule_alertmanager_will_load(self) -> None:
        """The equality that catches the whole class, whatever spelling the next one arrives in.

        Forbidding the legacy keys closes the route that was measured. This closes the CLASS: the
        number of rules this file's reader returns must equal the number of list entries the region
        holds, counted by indentation and so blind to which key opens each one. A rule in any
        spelling the parser cannot open makes the two disagree. `amtool check-config` prints the
        same figure, which is how the escape was found: amtool said three and :func:`inhibitions`
        said two.
        """
        region = inhibit_region()

        assert inhibit_entries(region) == len(inhibitions()), (
            f"the inhibit-rules region holds {inhibit_entries(region)} entries and this file's "
            f"reader sees {len(inhibitions())}. A rule it cannot open is a rule it cannot guard, "
            "and Alertmanager will honour it. Compare `amtool check-config`'s own count."
        )

    def test_every_alert_an_inhibit_rule_names_is_a_rule_that_exists(self) -> None:
        """A rule naming an alert that does not exist is dead, and a typo reads as one."""
        for rule in inhibitions():
            for matcher in (*rule.sources, *rule.targets):
                label, _, value = matcher.partition("=")
                if label != "alertname":
                    continue
                assert set(value.split("|")) <= set(SEVERITY_BY_ALERT), matcher

    def test_an_inhibit_rule_suppresses_fewer_alerts_than_the_deployment_has(self) -> None:
        """A rule that names most of the twelve as targets is a blanket rule spelled out longhand.

        The two guards above forbid a class matcher; they do not forbid enumerating eleven alerts.

        THE CAP IS ON WHAT AN INHIBITION IS, not on half the file. Half of twelve is six, and six of
        the twelve is SIX OF THE SEVEN WARNINGS: measured with both sides naming alertnames, so the
        both-sides guard does not help, one rule suppressed `SolveFailing`, `SourceStale`,
        `SupersededRatioHigh`, `ProbeSlow`, `AssemblySlow` and `HorizonNotMaintained` at once and
        this assertion passed. A cap at half the deployment does not bound the harm it exists to
        bound.

        Four is what an inhibition plausibly is: the largest rule this deployment ships names four,
        one cause making four duties redundant. A cause that makes five alerts redundant is a
        different design, and it should have to argue for itself here.
        """
        for rule in inhibitions():
            named = {
                name
                for matcher in rule.targets
                if matcher.startswith("alertname=")
                for name in matcher.partition("=")[2].split("|")
            }

            assert len(named) <= MOST_ALERTS_ONE_CAUSE_MAKES_REDUNDANT, (
                f"{rule.sources} suppresses {len(named)} alerts, past the "
                f"{MOST_ALERTS_ONE_CAUSE_MAKES_REDUNDANT} one cause plausibly makes redundant. "
                "That is a blanket rule enumerated rather than a cause."
            )


class TestLiveness:
    """Every process that exports a family must have an alert that fires when it stops.

    This deployment has shipped a whole process whose registry nothing scraped. The
    equivalent silence is a process nothing watches: every plan-pipeline, calendar and token family
    is recorded in the worker, so a dead worker leaves a frozen gauge reading healthy and an absent
    counter with no increase.

    THE FLOOR IS READ FROM `prometheus.yml`, not from `JOBS_BY_MEMBER`. That map is hand-maintained,
    so deriving the floor from it meant a sixth scrape job for a new process passed the whole suite
    unless someone also edited the map. Read from the scrape configuration, a job added anywhere
    fails until a rule watches it.
    """

    def test_every_job_of_ours_has_a_liveness_alert(self) -> None:
        ours = our_scrape_jobs()

        assert ours, "prometheus.yml declares no job of ours, so this floor reads nothing"
        assert ours <= liveness_jobs(), (
            f"{sorted(ours - liveness_jobs())} are scraped as processes of this application and no "
            "rule reads up{job=...} for them, so a stopped process leaves every rule over its "
            "families silent"
        )

    def test_every_liveness_matcher_names_a_job_the_scrape_configuration_declares(self) -> None:
        """The other direction: a matcher naming no job is a term that is always absent."""
        assert liveness_jobs() <= scrape_jobs()

    def test_the_member_map_names_only_jobs_of_ours(self) -> None:
        """The map is still crossed, so a row for an exporter or a typo cannot sit in it unseen."""
        declared_jobs = {job for jobs in JOBS_BY_MEMBER.values() for job in jobs}

        assert declared_jobs <= our_scrape_jobs()

    def test_every_member_that_declares_a_family_is_in_the_topology(self) -> None:
        """A member added to the workspace without a row here would escape the absent() guard."""
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
        """An exporter that is down reads as plenty of disk, a live database and a synced clock."""
        for name in ("DiskFillingUp", "DatabaseUnreachable", "ClockDrifting"):
            assert "absent(" in named(name).expr


class TestEveryMatcherNamesALabelItsFamilyCarries:
    """A matcher on a label the family does not declare cannot mean what it says.

    The quietest shape a rule can fail in, and the one `promtool check config` cannot see: the file
    is valid, the family exists, the threshold is sensible, and the matcher does something other
    than what it reads as. Which other thing depends on the operator, and the two are opposites: an
    equality selects nothing, so the term is silent, while a negation selects the whole series, so
    the filter is a no-op. `matchers_on_an_undeclared_label` records both with the operator.

    Five of this file's six label matchers read a family that declares the label, so the shape is
    settled and a sixth that does not is a defect rather than a style.

    Derived from both ends rather than listed, so a rule that gains a matcher and a family that
    loses a label are the same failure.
    """

    def test_the_only_matchers_that_cannot_mean_what_they_say_are_the_declared_ones(self) -> None:
        """An exact equality, so a new one fails and a repaired one fails too."""
        assert matchers_on_an_undeclared_label() == set(MATCHERS_ON_AN_UNDECLARED_LABEL)

    @pytest.mark.parametrize("entry", sorted(MATCHERS_ON_AN_UNDECLARED_LABEL))
    def test_each_declared_one_states_what_would_remove_it(self, entry: str) -> None:
        """A reason long enough to look like one is not a reason.

        Three things are derived from the entry's own key and crossed against the reason: the
        missing label, the member that DECLARES the family, since that is where the label has to be
        added, and THE CONSEQUENCE THE OPERATOR ACTUALLY HAS.

        The first version asserted a length alone, which any sentence of the right size satisfies.
        The second asserted the label and the member but left the consequence sentence free to say
        the opposite of what the operator does, so an entry could record a no-op matcher as a silent
        one and stay green.
        """
        _, family, matcher = entry.split(":")
        parsed = _KEYED_MATCHER.fullmatch(matcher)

        assert parsed is not None, f"{matcher!r} is not a label and an operator, so the key is bad"
        label, operator = parsed.group("label"), parsed.group("operator")
        member = declaring_member(family)
        reason = MATCHERS_ON_AN_UNDECLARED_LABEL[entry]

        assert member is not None, f"no member declares {family}, so nothing can be pointed at"
        assert len(reason) > 80
        assert label in reason, f"the reason does not name the missing label {label}"
        assert member in reason or member.replace("_", "-") in reason, (
            f"the reason does not name {member}, which is where the label has to be added"
        )
        assert _CONSEQUENCE_OF[operator] in reason, (
            f"the reason must state that this matcher {_CONSEQUENCE_OF[operator]}, because that is "
            f"what `{operator}` on a label the family does not declare does"
        )

    def test_the_reading_finds_the_labels_the_collectors_declare(self) -> None:
        """The positive control: an empty label map reports every matcher in the file as broken."""
        labels = declared_labelnames()

        assert labels["syncr_solve"] == frozenset({"outcome"}), "in the registry's own spelling"
        assert labels["syncr_learning_samples"] == frozenset({"tenant", "parameter"})
        assert labels["syncr_learning_run_duration_seconds"] == frozenset()

    def test_no_exempt_label_is_one_a_collector_declares(self) -> None:
        """The exemption is for labels the scrape and the client library add, so a label some family
        declares has no business in it: exempting one would blind the crossing to a real matcher."""
        declared_anywhere = frozenset().union(*declared_labelnames().values())

        assert _NOT_DECLARED_BY_A_COLLECTOR & declared_anywhere == frozenset()

    def test_the_reading_sees_a_selector_written_with_a_space(self) -> None:
        """Whitespace before the brace is valid PromQL, and both the crossing and the control below
        read this one pattern, so the tight-only spelling hid a real selector from both."""
        spaced = 'increase(syncr_learning_run_duration_seconds_count {outcome="failed"}[24h])'

        (found,) = _SELECTOR.finditer(spaced)
        assert found.group("family") == "syncr_learning_run_duration_seconds_count"
        assert found.group("matchers") == 'outcome="failed"'

    def test_every_family_a_matcher_reads_has_its_labels_read(self) -> None:
        """A family the reading cannot see is a family it steps over rather than judges."""
        labels = declared_labelnames()
        constrained = {
            base_family(found.group("family"))
            for rule in alert_rules()
            for found in _SELECTOR.finditer(rule.expr)
        }

        assert constrained, "no rule constrains a label, so this crossing asserts nothing"
        assert constrained <= set(labels) | declared(EXTERNALLY_PRODUCED)


class TestTheCrossing:
    """Both directions, derived, and each as an EXACT equality rather than a containment."""

    def test_every_family_shaped_literal_on_disk_is_in_the_registry(self) -> None:
        """The reading that sees a family an import cannot register.

        A collector constructed inside a function body never registers on import, so the registry
        walk alone cannot see it and both set differences would step over it while a running process
        exported it. Its NAME is on disk regardless, which is what this reads.

        Stated as an exact equality against the declared non-families, so a third noise name must be
        declared deliberately and a declaration for a name that IS a family fails.
        """
        assert family_literals() - exported_families() == declared(NOT_A_FAMILY)

    def test_no_declared_non_family_is_actually_a_family(self) -> None:
        """The other direction: a stale row here would hide a family from the whole crossing."""
        assert declared(NOT_A_FAMILY) & exported_families() == set()

    def test_every_exported_family_has_its_name_on_disk(self) -> None:
        """The trivial direction, asserted because it is the positive control for the scan.

        A scan that found nothing would satisfy the equality above by making both sides empty of
        everything except the declared noise.
        """
        assert exported_families() <= family_literals()

    @pytest.mark.parametrize("name", sorted(NOT_A_FAMILY))
    def test_each_declared_non_family_states_a_reason(self, name: str) -> None:
        assert len(NOT_A_FAMILY[name]) > 80

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
    """`SPEC_FAMILIES`, which no exemption can absorb.

    One constant rather than two overlapping lists. An empty reason puts the family on the floor; a
    reason lets it off, and the same family must then appear in `UNWATCHED` with its own. Escaping
    the floor therefore takes two deliberate statements in two places.
    """

    def test_every_family_the_spec_names_exists(self) -> None:
        assert {base_family(one) for one in SPEC_FAMILIES} <= exported_families()

    def test_every_family_the_spec_names_is_watched_unless_it_says_why_not(self) -> None:
        """A family with an empty reason is on the FLOOR rather than in a set of exemptions."""
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

        Writes are off in every deployment because no projection from an armed deployment has run
        over a horizon of real plan blocks, so every plan change produces a refusal recorded as a
        failure. The arming gauge is what separates 'syncr cannot write' from 'syncr is not
        permitted to write'.
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


class TestTheWriteTargetFiringConditions:
    """The three rules over the write target, each pinned at the condition it fires on.

    THE CONDITION, NOT THE FIRING: nothing here evaluates the expression, so these are controls over
    what the deployed rules are stated to be and not over what Prometheus does with them.

    Two rule blocks carry them: the token age and the projection failure, plus the contained
    per-tenant fault, which is folded into both as a disjunct rather than stated as a rule of its
    own. A contained fault leaves a gauge at its last value and its last value is the healthy one,
    so the disjunct is what stops a frozen gauge reading healthy, and it therefore belongs on the
    rule whose consequence it shares.

    EVERY ASSERTION HERE IS ON A PARSED TERM RATHER THAN ON A SUBSTRING. A threshold read out of the
    whole expression passes when the operator flips, when the window moves, and when the number
    turns out to bound a different disjunct.
    """

    def test_the_token_age_fires_on_any_non_zero_age_once_it_has_held_for_fifteen_minutes(
        self,
    ) -> None:
        """The gauge holds the age of the CONDITION, so a bare `> 0` is the condition.

        Read as a level and not over a range: the age grows by itself from the instant refreshing
        starts failing, so a rate or an increase over it would report zero on a stuck credential
        nobody has touched. The wait rides out a transient network refusal without waiting out a
        real expiry.
        """
        rule = named("WriteTargetTokenExpiring")
        term = comparison_on(rule, "syncr_write_target_token_age_seconds")

        assert (term.operator, term.threshold) == (">", 0.0)
        assert term.window == "", (
            "an age is a level; an increase over it reads zero when it is stuck"
        )
        assert rule.holds_for == "15m"
        assert rule.severity == "critical"

    def test_the_projection_fires_on_a_failure_in_its_window_and_only_while_writes_are_armed(
        self,
    ) -> None:
        """Both halves of the condition, because either one alone is an alert nobody can use.

        A refused projection is recorded as a failure deliberately, so the failure count alone fires
        on every plan change in a deployment whose writes are switched off, which is every
        deployment today. The arming state alone fires on nothing at all.
        """
        rule = named("ProjectionFailing")
        failures = comparison_on(rule, "syncr_projection_duration_seconds")
        armed = comparison_on(rule, "syncr_projection_writes_enabled")

        assert (failures.operator, failures.threshold, failures.window) == (">", 0.0, "15m")
        assert (armed.operator, armed.threshold) == ("==", 1.0)
        assert 'outcome="failed"' in rule.expr
        assert rule.holds_for == "5m"
        assert rule.severity == "critical"

    @pytest.mark.parametrize(
        ("name", "family"),
        [
            ("WriteTargetTokenExpiring", "syncr_observability_tenant_failures"),
            ("ProjectionFailing", "syncr_projection_tenant_failures"),
        ],
    )
    def test_a_contained_tenant_fault_fires_the_rule_whose_reading_it_freezes(
        self, name: str, family: str
    ) -> None:
        """The fault that is folded into both rules rather than stated as one, and its pairing.

        Each counter has to be read by the rule that goes quiet when its duty stops: the state duty
        contains a per-tenant fault and counts it, which leaves the token age at zero, and the
        projection duty does the same for a pass that raised outside its stated failures, which
        records nothing on the write target at all. A counter read by the wrong rule inherits the
        wrong wait and the wrong severity, and the frozen reading stays healthy.
        """
        term = comparison_on(named(name), family)

        assert (term.operator, term.threshold, term.window) == (">", 0.0, "15m")


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
        """The maintainer performs roughly 288 ASSEMBLIES AND PROBES a day.

        The assembly is the cost. A panel that named only the probes would understate the dominant
        one by an order of magnitude.
        """
        text = dashboard_text("system.json")

        assert "288 ASSEMBLIES AND PROBES" in text.upper()
        assert "THE ASSEMBLY IS THE COST" in text.upper()

    def test_the_product_dashboard_records_that_adherence_is_not_a_metric(self) -> None:
        """Optimizing it rewards under-planning, and the reason has to travel with the dashboard."""
        text = dashboard_text("product.json").lower()

        assert "adherence rate is deliberately absent" in text
        assert "under-planning" in text
