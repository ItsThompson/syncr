#!/usr/bin/env python3
"""Post one alert per severity to a running Alertmanager and report what it did with each.

THE ONE ARTEFACT `amtool check-config` CANNOT JUDGE. An inhibit rule whose matchers name a CLASS
rather than a cause is syntactically perfect and silences whole severities: this deployment shipped
exactly that, and only posting alerts showed it. A warning coming back `suppressed` beside an
unrelated critical is the failure to look for.

    deployments/bin/alertmanager-probe.py <base-url>

Written in Python rather than shell for a reason that is itself the ticket's own rule turned on its
own tooling. The first version was a shell script that piped into `python3`, run by its recipe in
`alpine/curl:latest`, WHICH HAS NO `python3`: it exited 127 having posted its four alerts and
reported nothing, so the probe for the defect that caused the round-1 must-fix had never once run
through its own recipe. One language, one image, and `stack-probe.py` is the model: `urllib` is in
the standard library, so the api's own image needs nothing installed.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

# One alert per severity, plus a second warning from a subsystem the critical shares nothing with.
# `BackupStale` is the critical that fires unconditionally on this deployment until ticket 58 writes
# its metric, so it is the one an inhibit rule is most likely to be reached for.
PROBES = (
    ("BackupStale", "critical"),
    ("ProbeSlow", "warning"),
    ("DiskFillingUp", "warning"),
    ("LearningJobFailed", "info"),
)

# How long to let Alertmanager settle before reading its own verdict back.
SETTLE_SECONDS = 2


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


def report(alerts: list[dict[str, object]]) -> bool:
    """Print each alert's state, and answer whether every warning was deliverable."""
    suppressed = []
    for alert in sorted(alerts, key=lambda one: one["labels"]["alertname"]):  # type: ignore[index,call-overload]
        labels = alert["labels"]
        status = alert["status"]
        print(
            f"  {labels['alertname']:<26}{labels['severity']:<10}"  # type: ignore[index]
            f"state={status['state']:<12}inhibitedBy={status['inhibitedBy']}"  # type: ignore[index]
        )
        if status["state"] == "suppressed" and labels["severity"] == "warning":  # type: ignore[index]
            suppressed.append(labels["alertname"])  # type: ignore[index]
    if suppressed:
        print(
            f"\nFAILED: {sorted(suppressed)} came back suppressed. An inhibit rule is silencing a "
            "CLASS rather than the named alerts one cause makes redundant."
        )
    return not suppressed


if __name__ == "__main__":
    import time

    url = sys.argv[1] if len(sys.argv) > 1 else None
    if url is None:
        print("usage: alertmanager-probe.py <base-url>")
        sys.exit(2)

    for name, severity in PROBES:
        post(url, name, severity)
    time.sleep(SETTLE_SECONDS)

    print(f"ALERTS POSTED TO {url}")
    sys.exit(0 if report(read(url)) else 1)
