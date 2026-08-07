#!/usr/bin/env bash
# Probe the deployed stack THROUGH THE TUNNEL, from outside the host.
#
# ONE DEFINITION, TWO CALLERS: `cd.yml` runs it after a deploy and `healthcheck.yml` runs it on a
# schedule. A scheduled probe that drifted from the deploy's own check would be two different claims
# about the same deployment.
#
# WHY IT RUNS OUTSIDE AT ALL. Prometheus, Alertmanager and Grafana are on the same host as the
# application, so a fully-down host cannot alert on itself. That is the one monitoring gap a single-host
# deployment has, and it is closed from outside rather than pretended away: this failing IS the
# notification, delivered by GitHub to the repository's own watchers.
#
# THREE REQUESTS, because each one can fail while the others pass:
#
#   /healthz   the api process is alive. NO dependency checks: a liveness probe that failed on a brief
#              database outage would restart a healthy process and turn a short outage into a long one
#   /readyz    the database is reachable AND the migration head is applied. This is the deploy gate
#   /          the frontend's document. Caddy serving the Vite build, which is what a browser gets;
#              `/readyz` says nothing about it, and an image with an empty /srv answers 404 here
#
# NOTHING IS PRINTED BUT STATUS CODES. The base URL is the tunnel hostname and it is a secret in both
# callers; a response body from `/readyz` names this deployment's checks. Neither belongs in a public
# log.
#
# THE RETRY IS NOT A SOFTENER. Three attempts over half a minute distinguishes "the deployment is down"
# from "one request was unlucky", and a scheduled alert that pages on an unlucky request is one whose
# recipient learns to ignore it. A deployment that is down fails all three.

set -uo pipefail

: "${BASE_URL:?BASE_URL must be the tunnel hostname, with no trailing slash}"

ATTEMPTS=3
BACKOFF_SECONDS=10
TIMEOUT_SECONDS=15

probe() {
  local path="$1"
  local attempt=1
  local status
  while [ "$attempt" -le "$ATTEMPTS" ]; do
    status="$(curl --silent --show-error --output /dev/null \
      --max-time "$TIMEOUT_SECONDS" --write-out '%{http_code}' \
      "${BASE_URL}${path}" 2>/dev/null)"
    if [ "$status" = "200" ]; then
      echo "  ${path} -> 200 (attempt ${attempt})"
      return 0
    fi
    echo "  ${path} -> ${status:-no response} (attempt ${attempt} of ${ATTEMPTS})" >&2
    attempt=$((attempt + 1))
    [ "$attempt" -le "$ATTEMPTS" ] && sleep "$BACKOFF_SECONDS"
  done
  return 1
}

echo "probing the deployment through the tunnel"
failed=0
for path in /healthz /readyz /; do
  probe "$path" || failed=1
done

if [ "$failed" -ne 0 ]; then
  cat >&2 <<'REASON'

THE DEPLOYMENT DID NOT ANSWER. Read which path failed above, because they mean different things:

  all three          the host is down, or the tunnel is not connected. A Cloudflare outage is a syncr
                     outage, which is the cost this deployment accepted for publishing no host ports.
                     docs/runbooks/deploy-and-rollback.md
  /readyz only       the api is alive and the database is unreachable, or the migration head is not
                     applied. docs/runbooks/database-unreachable.md
  / only             the api is fine and the frontend is not: Caddy is up with no build, or the tunnel's
                     ingress rule points at the wrong service.
REASON
  exit 1
fi

echo "the deployment answers /healthz, /readyz and / through the tunnel"
