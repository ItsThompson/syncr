# Deploying, and rolling back

## Conventions used below

```
cd /opt/syncr
DEPLOY="-f docker-compose.yml -f docker-compose.monitoring.yml -f docker-compose.deploy.yml -f docker-compose.tunnel.yml"
OPS="-f docker-compose.yml -f docker-compose.deploy.yml"
set -a; . deployments/digests.env; set +a     # the release's pinned images
```

### What pins what

Every image this deployment runs is a digest, and there are two places digests come from:

| Image | Pinned by |
|---|---|
| postgres, prometheus, grafana, alertmanager, the two exporters, cadvisor, cloudflared | a LITERAL digest in `docker-compose.deploy.yml`, reviewed beside its tag |
| `syncr-api`, `syncr-frontend`, `syncr-learning`, `syncr-ops` | `deployments/digests.env`, which `cd.yml` writes and `just deploy` records |

**Every `just` recipe reads that file itself**, so no operator has to remember an export: `just deploy`,
`just backup-now`, `just wal-ship`, `just learn-once` and `just restore-drill` all compose the pins by
default. A raw `docker compose` command does not, which is what the `set -a` line above is for. On a
host with no `deployments/digests.env`, compose stops with the missing variable's name rather than
building an image from the checkout.

## Trigger

Every release. Also the first deployment, which has eleven steps nothing else has.

## What a deploy is

```
cd.yml            builds and pushes both images, writes their DIGESTS to the host, runs `just deploy`
just deploy       pull, migrate as a one-shot, restart api/worker/frontend, WAIT FOR /readyz
on failure        re-deploy the previous digests, which are recorded because they are pinned
```

| Rule | Why |
|---|---|
| Images are pinned by **digest**, never by tag | A floating tag makes a redeploy an unreviewed change, and leaves a rollback with no version to name |
| Frontend and backend deploy **together** | One stack, one deploy. A version-skew window would be a problem invented rather than solved |
| Migrations run as a **one-shot before** api and worker start | Never at application startup, so two replicas cannot race |
| `/readyz` is the gate | It compares the applied revision against the head the checkout ships, so a deploy that did not migrate cannot serve traffic |
| Rollback is **re-deploying the previous digests** | Which is why `deployments/digests.previous.env` exists, and why it is written only after a deploy reaches readiness |
| A schema rollback is a **restore** | Migrations are forward-only. `restore-from-backup.md` |
| **No feature flags** | With one user and a single deployable, a flag is unnecessary indirection. Milestone sequencing served that purpose |

## The ordinary release

```
git tag v0.4.0 && git push --tags        # cd.yml runs on a tag, or manually
```

Then watch it, and if you are on the host instead:

```
just deploy
```

Verification, in the order that finds a problem:

```
just await-ready                              # /readyz, from inside: no host port is published
docker compose $DEPLOY ps                     # every service `running`, none restarting
curl -sS -o /dev/null -w '%{http_code}\n' https://<tunnel-host>/healthz    # through the tunnel
```

Then one screen in a browser. A stack that answers `/readyz` has a database and a migration head; it
has not been shown to render a week.

## Rolling back

`just deploy` does it for you when a deploy fails to reach readiness. By hand:

```
cp deployments/digests.previous.env deployments/digests.env
just deploy
```

**What rollback does not undo.** A migration that ran. The previous image against a migrated database
is exactly the case the two-release column-drop rule exists for: adding a column is safe to roll back
across, dropping one is not, which is why a drop is split across two releases. If the migration is the
problem, this is a restore rather than a rollback.

## The first deployment

Eleven steps, in order. Steps 3 and 9 need a person; nothing else does.

### 1. The host

Hetzner CX33: 4 vCPU, 8 GB RAM, 80 GB SSD. Debian or Ubuntu LTS.

### 2. Docker, just, and the checkout

Docker from Docker's own apt repository rather than Debian's `docker.io`, because the Compose plugin
and the engine have to come from the same place:

```
apt-get update && apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

`just` is NOT in Debian bookworm's repositories. Take the release binary, at a version you record, and
**record where it landed**: the systemd units resolve it through systemd's own `PATH`, which includes
`/usr/local/bin`, and `tests/test_deployment_figures.py` crosses this directory against every unit's
`ExecStart` so the two cannot disagree.

```
curl -fsSL https://github.com/casey/just/releases/download/1.42.4/just-1.42.4-x86_64-unknown-linux-musl.tar.gz \
  | tar -xz -C /usr/local/bin just
just --version                  # 1.42.4
command -v just                 # /usr/local/bin/just, which is on systemd's default PATH
```

This justfile has been parsed with **1.42.4** (the pin above) and with **1.50.0**. Both evaluate the
multi-line `env_var_or_default(` calls, and every recipe this runbook names dry-runs under both:
`deploy`, `backup-now`, `wal-ship`, `restore-drill`, `learn-once`, `digests`, `ports-check`,
`uid-check`. 1.50.0 was driven on the workstation that wrote this; 1.42.4 was driven by review.
Nothing in the tree crosses the two versions, so record a new one here when you move the pin.

```
git clone <repo> /opt/syncr && cd /opt/syncr
```

### 3. NTP, and the clock alert this deployment depends on

**The frame and the now rule are computed against the host clock.** A host half an hour ahead places
work in a week that has not started and marks blocks past that are still ahead: nothing fails, and
everything is wrong.

```
timedatectl set-ntp true
timedatectl show                      # NTPSynchronized=yes
```

`ClockDrifting` is the alert, and it reads the node exporter's own `node_timex_*` series. See
`clock-drift.md`.

### 4. The host secret file

`/opt/syncr/.env`, mode 0600, owned by root, **never in the repository**. Compose reads it for
interpolation and the api and worker read it as their environment. `.env.example` documents every key;
these are the ones without which the stack refuses to start or refuses to work:

| Key | What it is |
|---|---|
| `POSTGRES_PASSWORD` | The database credential. Unreachable from outside `data-net`, and still a real secret |
| `SESSION_SIGNING_SECRET` | Every browser session's identifier is keyed under it. Replacing it signs everyone out |
| `OAUTH_KEY_ENCRYPTION_KEY` | Encrypts the OAuth signing keys at rest. `just rotate-oauth-key` writes the file |
| `GOOGLE_OAUTH_CLIENT_SECRET` | The Google client. `google-oauth-verification.md` |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | Encrypts each stored refresh token. Rotating it costs the user a reconnect |
| `CLOUDFLARE_TUNNEL_TOKEN` | The only ingress credential |
| `RCLONE_CONFIG_OFFHOST_*` | The backup bucket. `rotate-secrets.md` lists all of them |
| `PUBLIC_BASE_URL` | The tunnel hostname. Every URL the Authorization Server publishes is built from it |
| `ALLOWED_ORIGINS` | The tunnel hostname. This plus `SameSite=Lax` is the whole CSRF defence |

**Confirm the secret scan catches a pasted one.** Two commands, because a clean tree only proves the
tree is clean.

**RUN THIS ON THE WORKSTATION THAT HOLDS THE CHECKOUT, not on the host.** Both commands need `uv` and a
synced Python environment, and step 2 installs neither: the host has no reason to hold a Python
toolchain, and the scan is a pre-commit and CI concern rather than a deployment one.

```
# 1. Prove the scan FIRES. A scratch file outside the repository, deleted immediately.
printf 'SECRET_KEY = "%s"\n' "$(openssl rand -base64 32)" > /tmp/scan-probe.py
uv run --no-sync detect-secrets-hook --baseline .secrets.baseline /tmp/scan-probe.py; echo "expect 1, got $?"
rm -f /tmp/scan-probe.py

# 2. And now the real tree, which must be clean.
just secret-scan
```

### 5. The backup recipient key

Generated **off the host**, and only the public half is copied to it:

```
# on a machine that is not the VPS:
gpg --quick-generate-key 'syncr backups <you@example.com>' default default never
gpg --armor --export 'syncr backups' > backup-recipient.asc
# keep the PRIVATE half in a password manager. It is what a restore needs.
scp backup-recipient.asc root@host:/opt/syncr/deployments/secrets/
```

### 6. The tunnel

In the Cloudflare dashboard: create a tunnel, note the token, and add **one** ingress rule:

```
<your-hostname>  ->  http://frontend:8080
```

One rule, because Caddy reverse-proxies the api paths and the browser talks to one origin. See
`frontend/Caddyfile`.

`/healthz` and `/readyz` are reachable through the tunnel by design: the external probe needs them, and
`probe-deployment.sh` prints status codes only. A `/readyz` body names the migration revision and
nothing else, which is within spec, and a Cloudflare Access policy on that one path is available if the
disclosure is ever unwanted.

### 7. The stack

```
just deploy
```

### 8. The first account

There is no sign-up in P0. `bootstrap-first-user.md`:

```
just bootstrap-user you@example.com
```

### 9. Prove nothing else is addressable

Two halves, and only the first is a machine's job:

```
just ports-check                    # no service in the resolved deployed stack publishes a port
```

**From another network**, against the host's public address:

```
nmap -Pn -p- <host-ip>              # expect: SSH, and nothing of syncr's
curl -sS http://<host-ip>:8000/     # expect: connection refused
curl -sS http://<host-ip>:5432/     # expect: connection refused
```

The tunnel hostname answers; the host's own address answers nothing but SSH. If a port is open, stop
and find out which service published it before going further: the database holds a complete map of the
user's life.

### 10. The timers

```
cp deployments/systemd/*.service deployments/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now syncr-backup.timer syncr-walship.timer syncr-learning.timer
systemctl list-timers 'syncr-*'
```

**Then START ONE SERVICE, not just its timer.** `systemctl list-timers` lists a timer whether or not
its service can execute at all, so enabling three timers and reading that list tells you nothing about
whether they will run. A unit whose `ExecStart` does not resolve fails at `203/EXEC` on its first
firing, which for the nightly backup is 03:00, and this is the step that would otherwise not notice:

```
systemctl start syncr-walship.service
systemctl status syncr-walship.service --no-pager      # expect: Active: inactive (dead), status=0/SUCCESS
journalctl -u syncr-walship.service -n 20 --no-pager   # expect: the shipper's own output
```

Then move both backup timestamps by hand, so `BackupStale` is quiet for a reason rather than by
accident. Each recipe reads `deployments/digests.env` itself, so these run the release's images:

```
just backup-now
just wal-ship
```

**These two succeed in an interactive shell whether or not the units work**, because a shell finds
`just` on `PATH` and a unit uses systemd's. That is why the `systemctl start` above is the check and
these two are not.

### 11. The restore drill

**Before the deployment is considered live.** `restore-from-backup.md`, and record the result.

## The monitoring stack, and two alerts that fire on day one

`BackupStale` and `LearningJobFailed` both read families written by a timer, and both carry an
`absent()` disjunct so they FIRE while their file is missing. That is the correct reading and it is
deliberate. So either install the timers before starting the monitoring stack, which step 10 does, or
post an Alertmanager silence **with an expiry** for those two alertnames.

## Operational costs this deployment accepted

Restated here because a release is when they are felt:

| Decision | Cost accepted |
|---|---|
| Postgres self-hosted | Backups, WAL archiving, tuning and a drill are owned here. That is this runbook and `restore-from-backup.md` |
| A single host | An hour of downtime is tolerable. There is no second one to fail over to |
| Cloudflare Tunnel as the only ingress | **A Cloudflare outage is a syncr outage.** The alternative is publishing ports on a host holding a complete map of the user's life |
| Monitoring on the same host | A fully-down host cannot alert on itself, which `healthcheck.yml` covers from outside |
| `learning` on a timer | A failed run is silent unless the timer's status is monitored, which it is |

## When the rollback also fails

You are in the case with no automated answer, and the order matters:

1. **Is the database intact?** `docker compose $DEPLOY exec postgres pg_isready`. If it is, this is an
   application problem and the previous digests are still in `digests.previous.env`.
2. **Bring the tunnel down** rather than leaving a half-deployed stack answering requests:
   `docker compose $DEPLOY stop cloudflared`. One user, an hour of downtime tolerated.
3. **Read the logs** before changing anything: `docker compose $DEPLOY logs --tail 200 api worker`.
4. If the migration is the cause, this is `restore-from-backup.md`, not a deploy.

## Not verified

- **No deployment exists yet.** Every command here is written from the Compose files, the workflows and
  the recipes rather than from a release: `just deploy` has never run against a Hetzner host, no
  Cloudflare tunnel has been created, and steps 1 through 11 have not been executed in order. Step 2's
  install commands in particular have never been run on a Debian host.
- **The external port scan in step 9 has not been run.** `just ports-check` has, and it reads the
  resolved configuration rather than the host.
- **`cd.yml` has never run.** It has no repository secrets to run with and no host to reach.
