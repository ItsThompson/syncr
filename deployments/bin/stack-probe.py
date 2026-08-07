#!/usr/bin/env python3
"""Report what Prometheus and Grafana actually did with the committed configuration.

Run against a stack brought up by `just monitoring`. It answers the four questions `promtool` and
`amtool` cannot: whether every scrape target is up, whether the rules loaded, whether Grafana
provisioned the four dashboards against the datasource they name, and whether the cadvisor memory
join returns a series.

    deployments/bin/stack-probe.py <prometheus-url> [grafana-url] [grafana-password]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from base64 import b64encode

EXPECTED_JOBS = frozenset({"syncr-api", "syncr-worker", "node", "cadvisor", "postgres"})

# The join the System dashboard draws container memory with. A panel over a join that returns
# nothing is a panel that says nothing, and neither name is ours to declare.
MEMORY_JOIN = (
    'container_memory_working_set_bytes{name!=""} / container_spec_memory_limit_bytes{name!=""}'
)


def fetch(url: str, *, auth: tuple[str, str] | None = None) -> dict[str, object]:
    request = urllib.request.Request(url)  # noqa: S310 - a URL this script was handed
    if auth is not None:
        token = b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=15) as answer:  # noqa: S310 - as above
        parsed: dict[str, object] = json.load(answer)
        return parsed


def report_targets(base: str) -> bool:
    data = fetch(f"{base}/api/v1/targets?state=any")["data"]
    targets = data["activeTargets"]  # type: ignore[index]
    print(f"SCRAPE TARGETS ({len(targets)})")
    healthy = set()
    for target in sorted(targets, key=lambda one: one["labels"]["job"]):
        job = target["labels"]["job"]
        print(f"  {job:<16}{target['health']:<10}{target['scrapeUrl']}")
        if target["health"] == "up":
            healthy.add(job)
    missing = EXPECTED_JOBS - healthy
    print(
        f"  -> {len(healthy)}/{len(EXPECTED_JOBS)} expected jobs up"
        + (f", MISSING {sorted(missing)}" if missing else "")
    )
    return not missing


def report_rules(base: str) -> bool:
    groups = fetch(f"{base}/api/v1/rules")["data"]["groups"]  # type: ignore[index]
    rules = [rule for group in groups for rule in group["rules"]]
    print(f"\nALERT RULES LOADED ({len(rules)})")
    for rule in sorted(rules, key=lambda one: one["name"]):
        print(f"  {rule['name']:<26}{rule['labels']['severity']:<10}state={rule['state']}")
    return len(rules) == 12


def report_query(base: str, query: str, *, label: str) -> bool:
    result = fetch(f"{base}/api/v1/query?query={urllib.parse.quote(query)}")["data"]["result"]  # type: ignore[index]
    print(f"\n{label}: {len(result)} series")
    for series in result[:6]:
        name = series["metric"].get("name") or series["metric"].get("job") or "-"
        print(f"  {name:<28}{series['value'][1]}")
    return bool(result)


def report_dashboards(base: str, password: str) -> bool:
    found = fetch(f"{base}/api/search?type=dash-db", auth=("admin", password))
    print(f"\nGRAFANA DASHBOARDS ({len(found)})")  # type: ignore[arg-type]
    for board in sorted(found, key=lambda one: one["title"]):  # type: ignore[call-overload]
        detail = fetch(f"{base}/api/dashboards/uid/{board['uid']}", auth=("admin", password))
        panels = detail["dashboard"]["panels"]  # type: ignore[index]
        uids = {
            target.get("datasource", {}).get("uid")
            for panel in panels
            for target in panel.get("targets", ())
        } | {panel["datasource"]["uid"] for panel in panels}
        uids = sorted(u for u in uids if u)
        print(f"  {board['title']:<26}{len(panels)} panels  datasource uids={uids}")
    return len(found) == 4  # type: ignore[arg-type]


if __name__ == "__main__":
    import urllib.parse

    prometheus = sys.argv[1]
    grafana = sys.argv[2] if len(sys.argv) > 2 else None
    password = sys.argv[3] if len(sys.argv) > 3 else "admin"

    outcomes = [
        report_targets(prometheus),
        report_rules(prometheus),
        report_query(prometheus, MEMORY_JOIN, label="CADVISOR MEMORY JOIN"),
        report_query(prometheus, "pg_up", label="POSTGRES pg_up"),
        report_query(
            prometheus, "syncr_db_pool_in_use", label="WORKER AND API syncr_db_pool_in_use"
        ),
    ]
    if grafana is not None:
        outcomes.append(report_dashboards(grafana, password))

    print(f"\n{sum(outcomes)}/{len(outcomes)} checks passed")
    sys.exit(0 if all(outcomes) else 1)
