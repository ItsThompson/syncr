#!/usr/bin/env bash
# Post one alert per severity to a running Alertmanager and report what it did with each.
#
# The one artefact `amtool check-config` cannot judge: it validates syntax, and an inhibit rule whose
# `equal:` names a label every alert shares is syntactically perfect and silences whole severities.
#
# Usage: bin/alertmanager-probe.sh <base-url>
set -euo pipefail

BASE="${1:?usage: alertmanager-probe.sh <base-url>}"

post() {
  local name="$1" severity="$2" subsystem="$3"
  curl -s -X POST "${BASE}/api/v2/alerts" -H 'Content-Type: application/json' -d "[{
    \"labels\": {
      \"alertname\": \"${name}\",
      \"severity\": \"${severity}\",
      \"subsystem\": \"${subsystem}\",
      \"deployment\": \"syncr\"
    },
    \"annotations\": {\"summary\": \"probe\", \"surviving\": \"probe\", \"runbook\": \"probe\"},
    \"startsAt\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }]" >/dev/null
}

# One critical that fires unconditionally on the shipped deployment, and one warning from an
# unrelated subsystem. If the warning comes back suppressed, no warning is deliverable.
post BackupStale critical backup
post ProbeSlow warning request-path
post DiskFillingUp warning host
post LearningJobFailed info learning

sleep 2
curl -s "${BASE}/api/v2/alerts?inhibited=true&silenced=false&active=true" \
  | python3 -c '
import json, sys
for alert in json.load(sys.stdin):
    labels = alert["labels"]
    status = alert["status"]
    print(
        f'"'"'{labels["alertname"]:<26}{labels["severity"]:<10}'"'"'
        f'"'"'subsystem={labels.get("subsystem", "-"):<14}'"'"'
        f'"'"'state={status["state"]:<11}inhibitedBy={status["inhibitedBy"]}'"'"'
    )
'
