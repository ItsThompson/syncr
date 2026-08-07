#!/usr/bin/env python3
"""Post every alert this deployment declares to a running Alertmanager and check what it suppressed.

THE ONE ARTEFACT `amtool check-config` CANNOT JUDGE. An inhibit rule whose matchers name a CLASS
rather than a cause is syntactically perfect and silences whole severities: this deployment shipped
exactly that, and only posting alerts showed it.

    deployments/bin/alertmanager-probe.py <base-url>

WHAT IT POSTS IS READ FROM `alerts.yml`, AND WHAT IT EXPECTS IS READ FROM `alertmanager.yml`. The
previous version posted four fixed names and failed on any suppressed warning, which was wrong
twice: it could not observe a rule sourced on any of the other eight, so the rule this deployment
added for `WriteTargetTokenExpiring` was invisible and it exited 0 whatever that rule said; and a
critical suppressed by a critical passed, though this deployment's own second rule targets
`ProjectionFailing`, which is a critical.

So the check is an EQUALITY rather than an emptiness: with every alert firing at once, the set
Alertmanager suppressed must be exactly the set the declared rules predict. That is what makes this
probe catch a rule its own reader cannot see. A rule in the legacy `source_match:` map form is
honoured by Alertmanager and missed by the reader below, so the observed set comes back LARGER than
the predicted one and the probe fails naming the difference.

Written in Python rather than shell for a reason that is itself the ticket's own rule turned on its
own tooling. The first version was a shell script that piped into `python3`, run by its recipe in
`alpine/curl:latest`, WHICH HAS NO `python3`: it exited 127 having posted its four alerts and
reported nothing, so the probe for the defect that caused the round-1 must-fix had never once run
through its own recipe. One language, one image, and `stack-probe.py` is the model: `urllib` is in
the standard library, so the api's own image needs nothing installed.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# How long to let Alertmanager settle before reading its own verdict back.
SETTLE_SECONDS = 2

_RULE = re.compile(r"^\s*- alert:\s*(?P<name>\w+)\s*$", re.MULTILINE)
_SEVERITY = re.compile(r"^\s*severity:\s*(?P<severity>\w+)\s*$", re.MULTILINE)
_TARGET_NAMES = re.compile(r'target_matchers:\s*\n\s*-\s*alertname\s*(?:=~|=)\s*"([^"]+)"')


def deployments() -> Path:
    return Path(__file__).resolve().parents[1]


def declared_alerts() -> list[tuple[str, str]]:
    """Every alert `alerts.yml` declares, with its severity, in file order.

    Read from the deployment rather than listed, so a rule added or a severity changed is exercised
    without this file being touched. Same file the test suite parses, same shape.
    """
    text = (deployments() / "prometheus" / "alerts.yml").read_text()
    openers = list(_RULE.finditer(text))
    bounds = [*(one.start() for one in openers), len(text)]
    found: list[tuple[str, str]] = []
    for position, opener in enumerate(openers):
        body = text[opener.end() : bounds[position + 1]]
        severity = _SEVERITY.search(body)
        found.append((opener.group("name"), severity.group("severity") if severity else "unknown"))
    return found


def predicted_suppressions() -> set[str]:
    """Every alert the declared inhibit rules say should be suppressed when all of them fire.

    Every rule's source is posted, because every declared alert is posted, so every rule is armed
    and its whole target list is predicted. Read from the `*_matchers:` spelling only, which is the
    point: Alertmanager honours more spellings than this reads, and the difference is what the probe
    reports.
    """
    text = (deployments() / "alertmanager" / "alertmanager.yml").read_text()
    _, _, region = text.partition("inhibit_rules:")
    region, _, _ = region.partition("\nreceivers:")
    return {name for found in _TARGET_NAMES.finditer(region) for name in found.group(1).split("|")}


def post(base: str, name: str, severity: str) -> None:
    body = json.dumps(
        [
            {
                "labels": {"alertname": name, "severity": severity, "deployment": "syncr"},
                "annotations": {"summary": "probe", "surviving": "probe", "runbook": "probe"},
                "startsAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ]
    ).encode()
    request = urllib.request.Request(  # noqa: S310 - a URL this script was handed
        f"{base}/api/v2/alerts", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=15):  # noqa: S310 - as above
        pass


def read(base: str) -> list[dict[str, object]]:
    query = "inhibited=true&silenced=false&active=true"
    with urllib.request.urlopen(  # noqa: S310 - as above
        f"{base}/api/v2/alerts?{query}", timeout=15
    ) as answer:
        parsed: list[dict[str, object]] = json.load(answer)
        return parsed


def report(alerts: list[dict[str, object]], predicted: set[str]) -> bool:
    """Print each alert's state, and answer whether Alertmanager did exactly what the file says.

    An equality in both directions. An UNEXPECTED suppression is a rule silencing something the
    deployment never declared, which is the defect that shipped. A MISSING one is a declared rule
    that is not taking effect, which is a rule that reads as protection and is not.
    """
    observed: set[str] = set()
    for alert in sorted(alerts, key=lambda one: one["labels"]["alertname"]):  # type: ignore[index,call-overload]
        labels = alert["labels"]
        status = alert["status"]
        print(
            f"  {labels['alertname']:<26}{labels['severity']:<10}"  # type: ignore[index]
            f"state={status['state']:<12}inhibitedBy={status['inhibitedBy']}"  # type: ignore[index]
        )
        if status["state"] == "suppressed":  # type: ignore[index]
            observed.add(str(labels["alertname"]))  # type: ignore[index]

    print(f"\n  declared rules predict suppressed: {sorted(predicted)}")
    print(f"  Alertmanager actually suppressed:   {sorted(observed)}")

    if unexpected := observed - predicted:
        print(
            f"\nFAILED: {sorted(unexpected)} came back suppressed and NO DECLARED RULE NAMES THEM. "
            "An inhibit rule is silencing a CLASS rather than the named alerts one cause makes "
            "redundant, or it is written in a spelling this file's reader cannot see."
        )
    if missing := predicted - observed:
        print(
            f"\nFAILED: {sorted(missing)} are named as targets by a declared rule and were NOT "
            "suppressed. That rule reads as protection and is not taking effect."
        )
    return not (unexpected or missing)


if __name__ == "__main__":
    import time

    url = sys.argv[1] if len(sys.argv) > 1 else None
    if url is None:
        print("usage: alertmanager-probe.py <base-url>")
        sys.exit(2)

    probes = declared_alerts()
    if not probes:
        print("FAILED: alerts.yml declared no rules, so this probe posted nothing")
        sys.exit(2)

    for name, severity in probes:
        post(url, name, severity)
    time.sleep(SETTLE_SECONDS)

    print(f"{len(probes)} ALERTS POSTED TO {url}")
    sys.exit(0 if report(read(url), predicted_suppressions()) else 1)
