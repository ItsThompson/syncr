# syncr dev and ops recipes.
#
# Recipes are grouped and this file stays appendable: a slice that adds a surface
# adds its own recipes to the right group rather than restructuring the file.
#
# Every member runs its own tools against the one shared root venv, so a recipe that
# targets a member cds into it and uses `uv run --no-sync`. `just setup` is what
# builds that venv.

# The dev stack is always the base compose file plus the dev overlay. The overlay
# carries overrides only and is never valid standalone.
dev_compose := "-f docker-compose.yml -f docker-compose.dev.yml"

# The monitoring stack is additive over the base file and never valid standalone: every service in
# it joins `app-net`, which the base file declares. Composed with the dev overlay for a local look
# and with the deploy overlay in production, which is one topology described two ways.
monitoring_compose := "-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.monitoring.yml"

# The deployed stack: the base file, the monitoring stack, the digest pins, and the tunnel. Every
# production recipe passes exactly this set, so "what is deployed" has one spelling.
deploy_compose := "-f docker-compose.yml -f docker-compose.monitoring.yml -f docker-compose.deploy.yml -f docker-compose.tunnel.yml"

# What the one-shot recipes below compose with. THE DIGEST PINS ARE IN THE DEFAULT, because every
# recipe here is one a runbook tells an operator to run on the deployed host, and a base-file-only
# composition resolves `syncr-api:latest` and `syncr-ops:latest`, which a digest pull NEVER creates:
# compose would then build them on the host, and the drill would prove the backup against an image
# the deployment does not run. `just drill-local` overrides this, because a development machine has
# no digests. See `docs/runbooks/deploy-and-rollback.md`, "what pins what".
ops_compose := env_var_or_default(
    "SYNCR_OPS_COMPOSE",
    "-f docker-compose.yml -f docker-compose.deploy.yml"
)

# The restore drill's own topology: a scratch Postgres, an api booted against it, and the same
# fingerprint reader the manifest was written with. Never composed with the tunnel: a drill has no
# business being reachable. Carries the pins for the reason above.
#
# Overridable so `just drill-local` can add the local-bucket overlay without a second copy of the six
# steps. A recipe that exists twice is a recipe that gets fixed once.
restore_compose := env_var_or_default(
    "SYNCR_RESTORE_COMPOSE",
    "-f docker-compose.yml -f docker-compose.restore.yml -f docker-compose.deploy.yml"
)

# The projects that hold something someone keeps: the developer's database, and the deployment's.
# They are what `dev_compose` and `deploy_compose` above resolve to, and
# `_refuse-a-retargeted-teardown` below is the only reader.
protected_projects := "syncr-dev syncr"

# Every Python member, in dependency order, so lint and test output reads bottom-up.
members := "packages/syncr-common packages/syncr-domain packages/syncr-solver packages/syncr-api packages/syncr-learning cli"

# List available recipes
default:
    @just --list

# --- Setup ------------------------------------------------------------------

# Build the shared root venv from the single root lockfile, install the frontend's locked
# dependency tree, and install the hooks
setup:
    uv sync --all-packages
    cd frontend && npm ci
    just hooks

# Install the git hooks.
#
# lefthook installs into git's *effective* core.hooksPath. A corporate agent may
# own that directory and make it unwritable, in which case a plain
# `lefthook install` fails, and the failure is easy to miss: the tree then commits
# with no formatter, linter, or secret scan. Point hooksPath at the repository's
# own hook directory for the install, then hand it back. Such agents delegate to
# .git/hooks, so their checks and lefthook's both run.
#
# The trap is load-bearing, not defensive dressing. A local core.hooksPath
# OUTRANKS the system value, so a borrowed setting left behind does not add
# lefthook on top of the corporate agent: it takes that agent out of the path
# entirely. A failed install without the trap therefore leaves the repository
# scanning nothing, which is the failure this recipe exists to prevent, and it
# wedges the recipe because a re-run sees a writable .git/hooks and takes the else
# branch. Restoring on every exit path also makes that stuck state unreachable.
hooks:
    #!/usr/bin/env bash
    set -euo pipefail
    # Check the VENV rather than the PATH. `uv run` prepends the venv's bin but does
    # not hide the rest of PATH, so a `command -v lefthook` preflight passes on a
    # system install that may predate the `no_auto_install` floor. The lockfile
    # carries that floor, so confirming the declared package is installed is the
    # whole check.
    uv pip show lefthook >/dev/null 2>&1 || {
        echo "lefthook is not in the venv; run 'uv sync --all-packages' first" >&2
        exit 1
    }
    # lefthook's generated hook script prefers a PATH binary over the venv's, so a
    # stale system install silently becomes what actually runs the hooks. Warn rather
    # than fail: it is the developer's PATH, not the repository's, but a shadow that
    # predates the no_auto_install floor must not be invisible.
    declared="$(uv pip show lefthook | awk '/^Version:/ {print $2}')"
    if system="$(command -v lefthook 2>/dev/null)" \
       && found="$("$system" version 2>/dev/null)" \
       && [ "$found" != "$declared" ]; then
        echo "warning: $system reports $found but this repository declares $declared;" >&2
        echo "         the installed hooks will prefer the PATH binary. Export" >&2
        echo "         LEFTHOOK_BIN=\"\$PWD/.venv/bin/lefthook\" or upgrade it." >&2
    fi
    if [ -n "$(git config --get core.hooksPath || true)" ] \
       && [ ! -w "$(git rev-parse --git-path hooks)" ]; then
        trap 'git config --local --unset core.hooksPath || true' EXIT
        git config --local core.hooksPath .git/hooks
        uv run --no-sync lefthook install --force
    else
        uv run --no-sync lefthook install
    fi

# --- Dev stack --------------------------------------------------------------

# The full dev stack: Postgres, the api with autoreload, and the worker.
#
# The stack comes up first and the migration one-shot runs after, so the api is briefly
# unready and its healthcheck says so. That ordering is a development convenience ONLY:
# section 21 requires the one-shot to complete BEFORE api and worker start, so the
# deploy path must not copy it.
dev:
    docker compose {{dev_compose}} up -d --build
    docker compose {{dev_compose}} run --rm api alembic upgrade head
    @echo "api on http://localhost:8000 · readiness: curl -s localhost:8000/readyz"

# Tear the dev stack down, keeping the pgdata volume
dev-down:
    docker compose {{dev_compose}} down

# REFUSE A TEARDOWN AN INHERITED PROJECT NAME WOULD RETARGET at a project that holds something.
#
# Compose resolves `COMPOSE_PROJECT_NAME` ABOVE the last `name:` in the `-f` list, and it takes that
# value from the shell environment first and from the project directory's `.env` second. So a name no
# recipe here mentions decides which project a teardown destroys: one gitignored line in `.env`, or
# one `export` in a developer's shell, retargets every teardown in this file at the deployment's
# volumes, and no tracked file changes.
#
# `just` does not read `.env` -- this file sets no `dotenv-load` -- so the file is read here rather
# than inherited, in compose's own precedence: the environment wins over the file, and the last
# assignment wins within it. Two spellings of that file compose's own reader accepts and a naive
# pattern does not: an `export ` prefix on the line, and a UTF-8 BOM before the first key. A `\r` at
# the end of a line is dropped for the same reason, so a CRLF file resolves rather than reading as
# unresolvable.
#
# BOTH OF THOSE ARE SCOPED THE WAY COMPOSE SCOPES THEM, which is why they are two `sed` anchors and
# not one deletion: compose forgives a mark only at the START OF THE FILE and a carriage return only
# as a LINE ENDING. Dropping either from anywhere makes this reading see an assignment compose does
# not honour, and the last such line would win: `COMPOSE_PROJECT_\rNAME=x` is a different key to
# compose and would have become this key here.
#
# `LC_ALL=C` BECAUSE COMPOSE'S READER IS BYTE-ORIENTED AND `sed` IS NOT. In a UTF-8 locale BSD `sed`
# aborts with `illegal byte sequence` at the first line that is not valid UTF-8 and reads no further,
# so one CP1252 password above this key emptied the reading and admitted the teardown while compose
# resolved the file without complaint. Reading bytes rather than characters is what makes the two
# agree, and it costs nothing: the pattern is ASCII.
#
# AND IT REFUSES WHAT IT CANNOT READ, which is what makes a narrow reading survivable rather than
# fatal. No pattern here can match compose's own reader: compose reads BYTES and also trims UNICODE
# whitespace before a key, and no single locale gives a text tool both. So when the file sets this key
# on a line this reading could not read, the answer is REFUSE rather than admit. Every way this
# reading has been found too narrow was a miss that would otherwise have admitted, and a refusal is
# one command away for whoever hits it while a teardown of the wrong project is not.
#
# A MENTION IS ANY LINE THAT IS NOT A COMMENT: a dotenv comment is a line whose FIRST non-blank
# character is `#`. A longer key such as `MY_COMPOSE_PROJECT_NAME` therefore counts as a mention and is
# REFUSED, which is a false refusal accepted on purpose. Excluding it was tried and reverted: the
# exclusion dropped the whole LINE rather than the occurrence, so `MY_COMPOSE_PROJECT_NAME="x"
# COMPOSE_PROJECT_NAME=syncr` stopped being seen at all and the teardown ran silently against the
# deployed project. A spurious refusal costs one `unset`; that cost the volumes.
#
# The condition is a POSITION rather than an emptiness. Compose acts on the LAST assignment IT sees,
# and `tail -n 1` takes the last assignment THIS PATTERN sees. Testing "did I read nothing" only
# catches the case where both sets are empty: one readable line above an invisible one left the
# pattern with a value, the emptiness test quiet, and compose acting on the line below. So the two
# line numbers are compared, and a mention BELOW the last match means this reading is behind compose.
#
# A MENTION IS A LINE THAT IS NOT A COMMENT AND NOT A LONGER KEY. A dotenv comment is a line whose
# FIRST non-blank character is `#`, which is why a `#` earlier in a value no longer hides an
# assignment after it. And the key must not be preceded by a word character, so `MY_COMPOSE_PROJECT_
# NAME` is a different key rather than this one wearing a prefix. That is how a byte copy of
# `.env.example` stays admitted while its own prohibition names the key.
#
# One divergence is deliberate and safe: compose treats an empty `COMPOSE_PROJECT_NAME` as SET and
# does not fall back to the file, while `${COMPOSE_PROJECT_NAME:-}` here treats it as unset and reads
# the file. That can only refuse where compose would have used the file's name, never admit.
#
# A NAME THIS READING CANNOT RESOLVE IS REFUSED. Compose interpolates the file's values, so one
# carrying `$` names a project decided somewhere this recipe cannot see, and the safe answer for a
# command that drops a project's volumes is no.
#
# A DEPENDENCY RATHER THAN A LINE OF EACH BODY, and the first one, because `just` runs dependencies
# left to right and nothing a teardown depends on should run before it is refused.
[private]
_refuse-a-retargeted-teardown:
    #!/usr/bin/env bash
    set -uo pipefail
    inherited="${COMPOSE_PROJECT_NAME:-}"
    if [ -z "$inherited" ] && [ -f .env ]; then
      # One spelling of the preprocessing, used by both readings below, so they cannot drift.
      strip=$'1s/^\xef\xbb\xbf//; s/\r$//; '
      assigns='^[[:space:]]*(export[[:space:]]+)?COMPOSE_PROJECT_NAME[[:space:]]*='
      inherited="$(LC_ALL=C sed -nE "$strip""s/${assigns}//p" .env | tail -n 1 | tr -d "\"'")"
      read_at="$(LC_ALL=C sed -nE "$strip""/${assigns}/=" .env | tail -n 1)"
      set_at="$(LC_ALL=C grep -n COMPOSE_PROJECT_NAME .env \
        | LC_ALL=C grep -vE '^[0-9]+:[[:space:]]*#' \
        | tail -n 1 | cut -d: -f1)"
      if [ -n "$set_at" ] && { [ -z "$read_at" ] || [ "$set_at" -gt "$read_at" ]; }; then
        echo "\`.env\` sets COMPOSE_PROJECT_NAME on line $set_at and this refusal cannot read that" >&2
        echo "line, so it cannot tell which project compose would act on. It refuses rather than" >&2
        echo "guess: this command drops a project's volumes, and compose reads that file before its" >&2
        echo "own. Any one of these clears it, and each is safe here:" >&2
        echo "  * delete line $set_at from \`.env\`;" >&2
        echo "  * REPLACE line $set_at with plain ASCII, no space of any kind before the key, rather" >&2
        echo "    than adding a line above it;" >&2
        echo "  * run \`export COMPOSE_PROJECT_NAME=<project>\` in this shell, which compose and this" >&2
        echo "    refusal both read before the file." >&2
        echo "If line $set_at only carries a LONGER key, such as MY_COMPOSE_PROJECT_NAME, rename it or" >&2
        echo "move it: this reads the line rather than the identifier, on purpose, because excluding a" >&2
        echo "longer key dropped the whole line and hid a real assignment beside it." >&2
        exit 1
      fi
    fi
    [ -n "$inherited" ] || exit 0
    if ! printf '%s' "$inherited" | grep -Eq '^[a-z0-9][a-z0-9_.-]*$'; then
      echo "COMPOSE_PROJECT_NAME is \`$inherited\`, which this refusal cannot resolve to a project:" >&2
      echo "compose interpolates it and would act on a project decided somewhere else. Unset it, or" >&2
      echo "spell the project out." >&2
      exit 1
    fi
    for held in {{protected_projects}}; do
      [ "$inherited" = "$held" ] || continue
      echo "COMPOSE_PROJECT_NAME names \`$held\`, which holds a database someone keeps, and compose" >&2
      echo "reads it above the \`-f\` list: this teardown would drop THAT project's volumes rather" >&2
      echo "than the ones this recipe is about. Unset it, in your shell and in \`.env\`." >&2
      exit 1
    done

# Tear the dev stack down AND drop its volumes, for a fresh Postgres
dev-reset: _refuse-a-retargeted-teardown
    docker compose {{dev_compose}} down -v

# Postgres only, published to localhost for the host-run inner loop
dev-infra:
    docker compose {{dev_compose}} up -d postgres

# The dev stack plus the monitoring stack: Prometheus, Alertmanager, Grafana, and the three
# exporters. Not part of `just dev`, because an inner loop should not pay 1.5 GB of monitoring
# stack to run a test.
#
# Nothing here publishes a host port, so reach a UI through the network rather than localhost:
#   docker compose {{monitoring_compose}} exec prometheus wget -qO- localhost:9090/-/healthy
monitoring:
    docker compose {{monitoring_compose}} up -d --build
    @echo "prometheus, alertmanager, grafana and three exporters are up on app-net"

# Tear the monitoring stack down, keeping its volumes
monitoring-down:
    docker compose {{monitoring_compose}} down

# Validate the Prometheus configuration and the thirteen alert rules, in the images that read them.
#
# A rule file the deployed Prometheus refuses is a deployment with no alerting at all, and the
# failure is silent: Prometheus logs it and carries on serving. `tests/test_alert_rules.py` parses
# the same files and crosses them against the metric registry, which is the half a linter cannot do.
monitoring-check:
    docker run --rm -v "$PWD/deployments/prometheus:/etc/prometheus:ro" \
      --entrypoint promtool prom/prometheus:v3.1.0 \
      check config /etc/prometheus/prometheus.yml
    docker run --rm -v "$PWD/deployments/alertmanager:/etc/alertmanager:ro" \
      --entrypoint amtool prom/alertmanager:v0.28.0 \
      check-config /etc/alertmanager/alertmanager.yml

# Ask the RUNNING stack what it actually did with the committed configuration.
#
# The three questions `promtool` and `amtool` cannot answer, and one of them cost this deployment
# every warning-severity alert it had:
#
#   - are all five scrape targets up, including the worker's own exposition
#   - did Grafana provision the four dashboards against the datasource they name
#   - does the cadvisor memory join return a series, or is the panel drawing nothing
#
# Needs `just monitoring` first. Run through `docker compose run`, which joins the compose networks
# itself: Prometheus and Grafana publish no host port, and asking `docker inspect` for the network
# name does not survive this file's own `{{ }}` interpolation, which is how the first version of the
# alert probe below came to be unrunnable.
monitoring-probe:
    docker compose {{monitoring_compose}} run --rm --no-deps \
      -v "$PWD/deployments/bin:/probe:ro" --entrypoint python api \
      /probe/stack-probe.py http://prometheus:9090 http://grafana:3000 "${GRAFANA_ADMIN_PASSWORD:-admin}"

# Post EVERY alert this deployment declares to the running Alertmanager and check what it suppressed.
#
# THE ONE ARTEFACT `amtool` CANNOT JUDGE. An inhibit rule whose matchers name a CLASS rather than a
# cause is syntactically perfect and silences whole severities: this deployment shipped exactly that,
# and only posting alerts showed it.
#
# The check is an EQUALITY, not an emptiness: with every rule firing, the set Alertmanager suppressed
# must be exactly the set the declared rules name as targets. That is what lets the probe catch a rule
# its own reader cannot see, which is how the legacy `source_match:` map form escaped every guard.
#
# Run in the api's own image, which has python, through `docker compose run`. The first version of
# this recipe used `alpine/curl`, which has no `python3`, so the probe exited 127 having posted its
# alerts and reported nothing: the probe for the defect that caused the round-1 must-fix had never
# once run through its own recipe. The WHOLE `deployments` directory is mounted rather than `bin`,
# because the probe reads both configuration files to decide what to post and what to expect.
monitoring-alert-probe:
    docker compose {{monitoring_compose}} run --rm --no-deps \
      -v "$PWD/deployments:/deployments:ro" --entrypoint python api \
      /deployments/bin/alertmanager-probe.py http://alertmanager:9093

# The api only, on the host, with autoreload. Needs `just dev-infra` and `just migrate`
dev-api:
    cd packages/syncr-api && uv run --no-sync uvicorn syncr_api.api.main:app \
      --host 127.0.0.1 --port 8000 --reload

# The worker only, on the host. Needs `just dev-infra` and `just migrate`
dev-worker:
    cd packages/syncr-api && uv run --no-sync syncr-worker

# The nightly learning job, once, against the dev database. A one-shot: it exits, and non-zero when
# any tenant's fit failed. Needs `just dev-infra` and `just migrate`
learn:
    cd packages/syncr-learning && uv run --no-sync python -m syncr_learning.entrypoint

# The Vite dev server. Proxies the api paths to `just dev-api`, so the browser talks to one
# origin and the client's `credentials: include` behaves as it will in the deployed stack
dev-frontend:
    cd frontend && npm run dev

# --- Migrations -------------------------------------------------------------
# The chain is forward-only with one head, and migrations run as a one-shot before
# the api and the worker start, never at application startup.

# Apply every migration up to head
migrate:
    cd packages/syncr-api && uv run --no-sync alembic upgrade head

# Autogenerate a revision from the model changes: just migration "add areas"
migration NAME:
    cd packages/syncr-api && uv run --no-sync alembic revision --autogenerate -m "{{NAME}}"

# Print the migration chain, so a second head is visible before it is a problem
migration-heads:
    cd packages/syncr-api && uv run --no-sync alembic heads

# --- Accounts ---------------------------------------------------------------

# Create the first tenant and user. P0 has no sign-up flow, so this is the only
# thing that creates an account. Needs migrations applied first.
#
# The password is prompted for, never taken as an argument: an argument would be in
# the shell history and in the process table. Set SYNCR_BOOTSTRAP_PASSWORD to script
# it. Re-running with the same email changes nothing and exits 0.
#
# See docs/runbooks/bootstrap-first-user.md
bootstrap-user EMAIL:
    cd packages/syncr-api && SYNCR_BOOTSTRAP_EMAIL="{{EMAIL}}" \
      uv run --no-sync syncr-bootstrap-user

# --- OAuth ------------------------------------------------------------------

# Create or rotate the OAuth signing keys at OAUTH_KEYS_PATH.
#
# Run it once on a new deployment to create the file, and on the rotation schedule after
# that. Rotation promotes the current key to previous and generates a new current: the
# JWKS publishes both, so tokens signed before the rotation keep verifying until they
# expire. The api reads the file at startup and never again, so RESTART THE API to pick
# the new key up.
#
# The file is encrypted with OAUTH_KEY_ENCRYPTION_KEY and written 0600. With
# OAUTH_KEYS_PATH empty this refuses rather than guessing a location.
#
# See docs/runbooks/rotate-oauth-signing-key.md
rotate-oauth-key:
    cd packages/syncr-api && uv run --no-sync syncr-rotate-oauth-key

# --- Tests ------------------------------------------------------------------

# Every backend suite. One failing member no longer hides the rest
test:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=0
    for member in {{members}}; do
      echo "--- $member"
      (cd "$member" && uv run --no-sync pytest) || failed=1
    done
    exit "$failed"

# The shared infrastructure suite. Pure, fast
test-common:
    cd packages/syncr-common && uv run --no-sync pytest

# The pure domain suite. Fast
test-domain:
    cd packages/syncr-domain && uv run --no-sync pytest

# The pure solver suite, including the zero-ML dependency boundary. Fast
test-solver:
    cd packages/syncr-solver && uv run --no-sync pytest

# The api suite. The integration tests need Postgres: `just dev-infra`
test-api:
    cd packages/syncr-api && uv run --no-sync pytest

# The offline learning suite. The storage tier needs Postgres: `just dev-infra`
test-learning:
    cd packages/syncr-learning && uv run --no-sync pytest

# The CLI suite
test-cli:
    cd cli && uv run --no-sync pytest

# The frontend unit suite, with coverage. The pre-push hook runs this
test-frontend:
    cd frontend && npm run test:coverage

# --- The E2E suite and the smoke-scenario harness ----------------------------
# The Playwright suite runs against the COMPOSE STACK rather than against a process this file
# starts, and the stack is its own compose project with its own volumes: a suite that empties a
# database must not be able to reach the one a developer is working against.
#
# NOTHING HERE PUBLISHES 5432. The dev overlay does, and a host-local Postgres owning
# 127.0.0.1:5432 and [::1]:5432 makes a compose route silently reach the wrong database. The e2e
# stack keeps Postgres on the base file's internal network with no host port at all, so the
# migrations run as a one-shot inside the network exactly as a deploy runs them.
#
# One published port, on 57080 by default: Caddy serves the built application and reverse-proxies
# the api paths, so the browser, the seeder and every API-level scenario reach the product through
# the ONE origin the deployed stack serves. Override it with SYNCR_E2E_PORT.

# Both files, in this order, so the project directory is the repository root
e2e_compose := "-f docker-compose.yml -f e2e/docker-compose.e2e.yml"

# The clock shift `just e2e-clock` records, and the one file it is recorded in. The e2e overlay's
# `env_file` entries read it, so a shift survives an `e2e-down`/`e2e-up` cycle until it is put
# back; this recipe is its only writer.
clock_offset_env_file := "e2e/clock-offset.env"

# Install the suite's locked dependency tree and the browser it drives.
#
# `--with-deps` because Playwright's bundled Chromium needs system libraries a Linux CI image does not
# guarantee, and this recipe is what the `e2e` job runs. On macOS the flag is a no-op.
e2e-setup:
    cd e2e && npm ci
    cd e2e && npx playwright install --with-deps chromium

# The harness's own static gates. `just lint` iterates the six Python members plus `deployments`, and the
# frontend hook globs `frontend/**`, so without this recipe nothing but tsc reads 4000 lines of
# TypeScript.
#
# The two statement checks are the ones worth having, and they are keyed on different things.
# `docs/smoke-scenarios.md` is the map from section 22's done-criteria table to something that can fail,
# and a row claiming an assertion no file makes is a list disagreeing with the fact it copies. It reads
# every column it is meant to bound, in both directions, and takes its titles from `playwright test
# --list` rather than from a regex over the source, because a regex counted a commented-out case as
# coverage. `e2e/scenarios.md` is the same discipline keyed on the FILE rather than on the scenario, which
# is the direction that can account for a spec driving none of the 37 and can notice a new spec at all.
#
# Every check runs even when an earlier one fails: one red linter must not hide the rest. Same shape as
# `lint-style`, comment included, so the pattern is recognisable as the same one.
lint-e2e:
    #!/usr/bin/env bash
    set -uo pipefail
    cd e2e
    failed=0
    for check in lint:format lint:scenarios lint:spec-scenarios; do
      echo "--- $check"
      npm run --silent "$check" || failed=1
    done
    exit "$failed"

# Bring the stack up and migrate it. Run this before any seed or any suite
e2e-up:
    docker compose {{e2e_compose}} up -d --build --wait postgres frontend ics-provider worker
    docker compose {{e2e_compose}} run --rm --no-deps api alembic upgrade head
    docker compose {{e2e_compose}} up -d --wait api
    @echo "e2e stack on http://localhost:${SYNCR_E2E_PORT:-57080} · readiness: curl -s localhost:${SYNCR_E2E_PORT:-57080}/readyz"

# Tear the e2e stack down AND drop its volumes. Its database is scratch by definition
e2e-down: _refuse-a-retargeted-teardown
    docker compose {{e2e_compose}} down -v

# The whole suite. Every scenario names its scenario number in its title
e2e:
    cd e2e && npx playwright test

# One scenario or one file, by title or path: `just e2e-only S10`
e2e-only pattern:
    cd e2e && npx playwright test {{pattern}}

# Shift the stack's clock by `offset`, or put it back with `PT0S`: `just e2e-clock P3D`.
#
# The offset is SYNCR_CLOCK_OFFSET, which `syncr_api.core.clock` reads and nothing else in the
# tree sets; the overlay passes it to api and worker and to nothing else, because those two are
# the processes that hold readers. A shift is STACK STATE, not test state: it is written to
# {{clock_offset_env_file}} and so outlives whatever asked for it, which is why the Playwright
# `clock` project owns putting it back (see `e2e/tests/harness.ts` for the rule).
#
# The value is validated through the reader itself BEFORE anything moves, so a misspelled
# duration fails here with that reader's own message rather than failing a container boot later.
# An empty value means no offset, so `just e2e-clock ""` restores as well as `PT0S` does.
e2e-clock offset:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose {{e2e_compose}} run --rm --no-deps \
      -e SYNCR_CLOCK_OFFSET="{{offset}}" api \
      python -c "from syncr_api.core.clock import clock_offset; clock_offset()" >/dev/null
    printf 'SYNCR_CLOCK_OFFSET=%s\n' "{{offset}}" > {{clock_offset_env_file}}
    docker compose {{e2e_compose}} up -d --wait api worker
    echo "stack clock shifted by '{{offset}}' · restore with: just e2e-clock PT0S"

# tsc over the harness. vitest is not what runs here, but the same rule applies: Playwright
# transpiles with esbuild and strips types without checking them
typecheck-e2e:
    cd e2e && npx tsc --noEmit

# --- Fixtures ---------------------------------------------------------------
# Each recipe loads ONE fixture from nothing: it empties the database, provisions the tenant
# through the console script a first deployment runs, declares the fixture over the HTTP API, and
# ticks the plan-horizon maintainer so the weeks inside the horizon hold a plan.
#
# SELF-CONTAINED ON PURPOSE, one command each. The ordering matters -- the tick must follow the
# declarations -- and a recipe with four lines would put that ordering in a file no test reads.
#
# THE DECLARATIONS GO THROUGH THE API, not through SQL. A SQL seed restates the schema and can
# write a row the product cannot; a fixture written through the API is one whose every value passed
# the same validation a user's would.
#
# Five of these fixtures also exist as frozen values in `syncr_domain.fixtures`, read by the domain
# and api suites. The numbers are taken FROM those modules rather than restated here, through
# `e2e/harness/constants.py`, so a fixture that stops straddling its gap breaks in one place.

# The week every other question is asked about: 61-ish blocks, a frame span, a compact block, an
# interview anchor with prep, transit and recovery, an anchor conflict, and a queue binding
seed-reference:
    node e2e/src/seed/cli.ts reference_week

# A spring-forward week and a fall-back week, each with a Sunday-night frame span crossing the ISO
# week boundary. Prints the two week identifiers: at most one is ever inside the horizon
seed-dst-weeks:
    node e2e/src/seed/cli.ts dst_weeks

# A Friday-to-Monday off-plan span with keepFrame false
seed-off-plan-week:
    node e2e/src/seed/cli.ts off_plan_week

# A sleep routine whose minimum is below its target, and a week that needs the give
seed-elastic-sleep:
    node e2e/src/seed/cli.ts elastic_sleep

# A task with a deadline and half its estimate already pinned, plus a past block left unconfirmed
seed-partial-progress:
    node e2e/src/seed/cli.ts partial_progress

# Two anchor types at the same wall time, one post_scope areas and one post_scope all
seed-recovery-scopes:
    node e2e/src/seed/cli.ts recovery_scopes

# The Interview, Exam and Lecture types with their real leads, durations and buffers
seed-shadow-geometry:
    node e2e/src/seed/cli.ts shadow_geometry

# Outcomes recorded on every block the horizon's weeks have ended. Prints what it reached.
# Every week solves; any failure stops the seed.
seed-maturity-corpus:
    node e2e/src/seed/cli.ts maturity_corpus

# A week whose declared floors sit just inside its remaining capacity, which is what makes a floor
# reservation observable at all: 1470 discretionary minutes against 960 minutes of floor
seed-tight-capacity:
    node e2e/src/seed/cli.ts tight_capacity

# A week with no frame at all, owing more before one deadline than the longest week could hold, so the
# span a verdict measures capacity over is readable as a figure at every instant of every week
seed-owes-more-than-a-week:
    node e2e/src/seed/cli.ts owes_more_than_a_week

# Tick the plan-horizon maintainer once, now. S1's "or trigger it": the wait is fifteen minutes,
# because the runner's first tick only sets its own due time
e2e-tick:
    docker compose {{e2e_compose}} run --rm --no-deps worker python /harness/tick.py

# --- Lint and format --------------------------------------------------------

# Every static gate: ruff, the format check, mypy, the deployment's own package, the hook config,
# and the invariant-label census
lint: lint-style typecheck lint-ops lint-hooks lint-invariants

# ruff check plus the format check over every member
lint-style:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=0
    for member in {{members}}; do
      echo "--- $member"
      (cd "$member" && uv run --no-sync ruff check . && uv run --no-sync ruff format --check .) \
        || failed=1
    done
    exit "$failed"

# mypy over every member. The pre-push hook runs this
typecheck:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=0
    for member in {{members}}; do
      echo "--- $member"
      (cd "$member" && uv run --no-sync mypy) || failed=1
    done
    exit "$failed"

# The deployment's own `ops` package: ruff at ITS language version, and mypy at the runtime's.
#
# `just lint-style` iterates the six workspace members and `deployments` is not one, so nothing in
# `just lint` or in CI ever entered that directory: measured, a PEP 695 `type` alias placed there
# passed mypy at 3.12 and was caught only by a hand-run `ruff check`, which left `deployments/ruff.toml`
# enforced by a skippable pre-commit hook alone. That file exists for exactly one reason, in its own
# header: `ops` runs on the Python `postgres:16.10-bookworm` carries, and a 3.12 construct there is a
# SyntaxError on `import ops.dump` at 03:00 inside a container.
#
# mypy is run a SECOND time here, at 3.11, because the api member's own invocation type-checks this
# package at 3.12 and therefore accepts what the image cannot parse. The two together are what make the
# language version a gate rather than a comment.
lint-ops:
    cd deployments && uv run --no-sync ruff check .
    cd deployments && uv run --no-sync ruff format --check .
    cd deployments && uv run --no-sync mypy --python-version 3.11 --strict ops

# Validate lefthook.yml. Nothing else reads it, and with no_auto_install the
# installed hooks can drift from the file, so a malformed config must fail a gate
# rather than a developer's next commit
lint-hooks:
    uv run --no-sync lefthook validate

# The invariant-label census, the lookup that has to resolve every label it finds, and ruff and mypy
# over `tools/` itself.
#
# A comment citing an invariant by its number points at a document this repository does not contain,
# and `docs/invariants.md` is the only thing that resolves one. The census reads the index and fails
# in two directions: a label with no row there, and a label named in a comment at all, outside the
# trees `PENDING` lists as still naming them. So a reader meets the requirement rather than a number,
# and a tree that has been swept cannot quietly acquire one again.
#
# `tools/` is not a workspace member, so `just lint-style` and `just typecheck` never enter it, which
# is the same hole `lint-ops` exists to close for `deployments/`. Its tests run here too rather than
# in a member's suite, because the scan belongs to no member and this is where its gate runs.
lint-invariants:
    uv run --no-sync python tools/invariant_labels.py --check
    uv run --no-sync pytest tools
    uv run --no-sync ruff check tools
    uv run --no-sync ruff format --check tools
    uv run --no-sync mypy --strict tools

# Format and apply safe fixes over every member
fmt:
    #!/usr/bin/env bash
    set -euo pipefail
    for member in {{members}}; do
      (cd "$member" && uv run --no-sync ruff format . && uv run --no-sync ruff check --fix .)
    done

# Every frontend static gate. The pre-commit hook runs this, and so does CI, so the hook and
# the gate cannot drift.
#
# The checks, none of which the others can cover:
#   oxlint          the language and React rules, plus the kit's import zones by SPECIFIER
#   stylelint       the design rules that live in CSS: no raw color, no motion, no radius
#   prettier        formatting, so twenty tickets of TypeScript accumulate no drift
#   tokens-validate the token layer, the sheets that render from it, and the theme that reads it
#   lint-markup     the design rules that reach the DOM as a class name or a data attribute
#   check-channels  each state channel assigned in exactly one file under the kit
#   check-imports   the kit's import zones again, by RESOLVED DIRECTORY rather than by specifier
#   check-contract  every field the document declares on a response, against what the generated
#                   client hands back
#   check-bundle    the built stylesheet, declaration by declaration, read with postcss
#   audit-contrast  every ink against every surface, computed, against the committed ledger
#   check-render    a RENDERED PIXEL, in a headless browser, over the built stylesheet
#
# Three of them overlap deliberately, because each takes a different INPUT and each input has a blind
# spot the others cover. oxlint matches a specifier's spelling, and three holes reached review that
# way: a barrel it did not name, a `.ts` extension, a `.js` extension resolving to a `.ts` file.
# check-imports resolves each import against the filesystem and asks which directory the file
# actually lives in. check-bundle reads the artifact: a banned utility named in a comment, in a plain
# string or in a `__fixtures__` file reaches the stylesheet a browser downloads without ever being a
# class on an element, which is how `backdrop-filter` shipped for three review iterations with every
# other check green.
#
# THE ONE THAT READS A COMPOSED RESULT is check-render, which is the one input none of the others has. Every
# one of them reads a declaration, a class list, an attribute or the built text, and all three real defects on
# the week grid were compositions: a `border` shorthand collapsing three edges into four, the same
# shorthand taking the Area's 2px top rule, and `-webkit-line-clamp` supplying an end-ellipsis that no
# reading of `white-space` or `text-overflow` could see. Each was found by a person opening a browser
# once, and 2216 tests were green through all three.
#
# IT REFUSES RATHER THAN SKIPS WHEN NO BROWSER IS PRESENT. A check that passes when it cannot look
# reports a claim it never tested, which is the suppression shape this repository has been bitten by
# twice. No browser is a declared dependency: the check probes the ones a developer already has, and
# GitHub's ubuntu runner images ship `/usr/bin/google-chrome`, which is one of the paths it probes. An
# operator on a machine with neither points SYNCR_CHROME at one.
#
# IT RUNS IN THE PRE-COMMIT HOOK, AND THAT IS A COST STATED RATHER THAN HIDDEN: the whole recipe measures
# 17 seconds with it and 6 without, because it builds the stylesheet a second time and invokes Chromium
# twice. It stays here anyway. This recipe IS the hook, and moving the one gate that reads a pixel to
# pre-push or to CI alone would leave it unarmed exactly where the three defects it exists to catch were
# written. Ten seconds a commit is the price of the input none of the others has.
#
# THE RECIPE COUNTS ITS OWN CHECKS AND SAYS SO AT THE END, and that is not decoration. Most of them print
# `ok` themselves and some are third-party tools with their own success lines, so a reader counting `ok`
# counted fewer than ran, and a check that had silently stopped running looked exactly like the ones that never
# said it. The tail line names how many ran, which is the figure a hard-coded count would have contradicted.
#
# Every check runs even when an earlier one fails: one red linter must not hide the rest.
lint-frontend:
    #!/usr/bin/env bash
    set -uo pipefail
    cd frontend
    failed=0
    ran=0
    for check in lint:js lint:css lint:format lint:tokens lint:markup lint:channels lint:imports lint:contract lint:bundle lint:contrast lint:render; do
      echo "--- $check"
      ran=$((ran + 1))
      npm run --silent "$check" || failed=1
    done
    if [ "$failed" -eq 0 ]; then
      echo "--- $ran check(s) ran, all ok"
    else
      echo "--- $ran check(s) ran, at least one FAILED" >&2
    fi
    exit "$failed"

# Apply the frontend formatter. The Python members' equivalent is `just fmt`
fmt-frontend:
    cd frontend && npm run --silent fmt

# The token file validator, standalone. A broken comment in a token file is a silent, total
# failure: it discards every declaration after it and renders a plausible page with no values
tokens-validate:
    cd frontend && npm run --silent lint:tokens

# Rewrite docs/design/contrast-ledger.md from the tokens. The check that it is current runs in
# `lint-frontend`; this is how a retuned pigment's new ratios are committed
contrast-ledger:
    cd frontend && node scripts/audit-contrast/cli.ts --write

# tsc over the frontend. Separate from `lint-frontend` because it is a whole-tree check and
# belongs with the other whole-tree checks at pre-push. It is not optional: vitest transpiles
# with esbuild, which strips types without checking them, so a green suite says nothing at all
# about type safety
typecheck-frontend:
    cd frontend && npm run --silent typecheck

# --- Contract ---------------------------------------------------------------
# The frontend never hand-writes a response type. `openapi.json` is generated from the FastAPI
# app and `schema.d.ts` from that, both committed, and a CI job regenerates both and fails on a
# diff, so a backend change that alters the contract cannot merge without the frontend seeing it.

# Regenerate frontend/openapi.json and frontend/src/api/schema.d.ts. Commit both
contract:
    cd packages/syncr-api && uv run --no-sync python scripts/export_openapi.py \
      ../../frontend/openapi.json
    cd frontend && npm run --silent codegen
    @echo "regenerated. commit frontend/openapi.json and frontend/src/api/schema.d.ts together"

# --- Security ---------------------------------------------------------------

# The audit gate fails on ANY advisory rather than only on high severity. `uv audit`
# has no severity threshold, and its JSON schema is explicitly preview and may
# change, so parsing a severity out of it would be a gate that silently stops
# working. Failing on any advisory is strictly stronger and cannot rot. Suppress a
# specific finding by adding `--ignore <ID>` below with a comment saying why.

# Scan both locked dependency graphs for known advisories
audit: audit-python audit-js

# The Python graph. Any advisory, per the reasoning above
audit-python:
    uv audit --preview-features audit-command

# The JS graph, at TWO thresholds, because the two halves carry different risk and npm
# offers no per-advisory suppression the way `uv audit --ignore` does.
#
# Production dependencies are held to `info`, which is npm's lowest level and so the literal
# "any advisory" reading that matches the Python gate. Those are the packages that reach a
# browser, so an advisory there is a shipped defect.
#
# The whole graph, dev tooling included, is held to high and above. That is deliberately
# weaker than the Python gate and the reason is npm, not appetite: there is no
# `--ignore <ID>`, so a moderate advisory in a transitive build dependency could not be
# suppressed with a comment saying why. It would have to be pinned through an `overrides`
# block, which is a change to the resolved graph made under time pressure by whichever
# ticket happened to be open. A gate that cannot be answered honestly gets answered by
# weakening it, so this one states its threshold instead.
#
# WHEN THIS GOES RED, the sanctioned response is, in order: `npm audit fix` if it resolves
# within the declared ranges; then a version bump of the direct dependency that pulls the
# advisory in, committed with the advisory ID in the message; then, only if neither works, an
# `overrides` entry in package.json with a comment naming the advisory and why the pin is
# safe. Never lower the threshold in this recipe to make a red gate green.
#
# Counts, reproducible from `npm audit --json` metadata: 11 production and 394 total
# dependencies, 0 advisories at every severity.
audit-js:
    cd frontend && npm audit --omit=dev --audit-level=info
    cd frontend && npm audit --audit-level=high

# The scan the pre-commit hook runs on staged files, over the whole tree
secret-scan:
    git ls-files -z | xargs -0 uv run --no-sync detect-secrets-hook --baseline .secrets.baseline

# Re-baseline a reviewed finding. Run this, confirm every new entry is genuinely
# not a secret, then commit the baseline with the change that introduced it.
secret-baseline:
    uv run --no-sync detect-secrets scan --baseline .secrets.baseline --exclude-files '^\.venv/'
    @echo "review the new entries in .secrets.baseline before committing"

# Assert the zero-ML rule at runtime. Split per image so CI keeps per-step failure
# attribution while each check has exactly one definition: the workflow calls these
# recipes rather than inlining the same docker commands.
#
# Each control comes FIRST, because a bare negative assertion reads any non-zero exit as
# a held boundary, including a container that never started.

# Both image boundaries: each image runs, and neither can import what it must not
image-boundary: image-boundary-api image-boundary-learning

# The api image must import its own stack and must NOT be able to import scipy
image-boundary-api:
    #!/usr/bin/env bash
    set -euo pipefail
    docker build -f packages/syncr-api/Dockerfile -t syncr-api:boundary-check .
    docker run --rm --entrypoint python syncr-api:boundary-check \
      -c "import fastapi, sqlalchemy, syncr_api, syncr_solver, syncr_domain, syncr_common"
    if docker run --rm --entrypoint python syncr-api:boundary-check -c "import scipy"; then
      echo "scipy is importable in the api image: the zero-ML boundary is broken" >&2
      exit 1
    fi
    echo "api image boundary holds, and the image runs"

# The learning image must import its own package and must NOT be able to import fastapi
image-boundary-learning:
    #!/usr/bin/env bash
    set -euo pipefail
    docker build -f packages/syncr-learning/Dockerfile -t syncr-learning:boundary-check .
    docker run --rm syncr-learning:boundary-check \
      python -c "import syncr_learning, syncr_domain, syncr_common"
    if docker run --rm syncr-learning:boundary-check python -c "import fastapi"; then
      echo "fastapi is importable in the learning image: the offline boundary is broken" >&2
      exit 1
    fi
    echo "learning image boundary holds, and the image runs"

# --- Deployment -------------------------------------------------------------
# One host, one Compose stack, one ingress. Every recipe here runs against the LIVE stack, so each
# one says what it is doing as it goes and none of them is silent about a failure.

# Print the current digest of every third-party image the deploy overlay pins.
#
# A base-image refresh is a DELIBERATE, REVIEWED change rather than a rebuild side effect, so this
# prints and never edits: paste a digest into `docker-compose.deploy.yml` beside the tag it belongs
# to, in a commit that says why the image is moving.
digests:
    #!/usr/bin/env bash
    set -uo pipefail
    for reference in \
      postgres:16.10-bookworm \
      prom/prometheus:v3.1.0 \
      prom/alertmanager:v0.28.0 \
      grafana/grafana:11.5.1 \
      prom/node-exporter:v1.8.2 \
      gcr.io/cadvisor/cadvisor:v0.52.1 \
      prometheuscommunity/postgres-exporter:v0.16.0 \
      cloudflare/cloudflared:2026.7.3 \
      caddy:2.11.4-alpine \
      node:22.22-bookworm-slim; do
      printf '%-50s %s\n' "$reference" \
        "$(docker buildx imagetools inspect "$reference" 2>/dev/null | awk '/^Digest:/{print $2; exit}')"
    done

# Assert that no service in the deployed stack publishes a host port.
#
# THE TUNNEL IS THE ONLY INGRESS, and this is the half of that claim a machine can check: it reads the
# resolved configuration of the whole deployed stack and fails on any published port. The other half
# is a scan FROM OUTSIDE the host, which only a person on another network can run;
# `docs/runbooks/deploy-and-rollback.md` carries it as a step of the first deployment.
ports-check:
    #!/usr/bin/env bash
    set -uo pipefail
    # EVERY profile, or the set this reads is not the set it claims to bound: `docker compose config`
    # omits a profile-gated service entirely, and three of the deployed services are gated.
    resolved="$(SYNCR_API_DIGEST=unset SYNCR_FRONTEND_DIGEST=unset SYNCR_LEARNING_DIGEST=unset \
      SYNCR_OPS_DIGEST=unset CLOUDFLARE_TUNNEL_TOKEN=unset \
      docker compose {{deploy_compose}} --profile ops --profile scheduled config)" || exit 1
    # A resolution that returned nothing would otherwise pass this recipe: the absence of a published
    # port in an empty document is not the property being checked.
    #
    # COUNTED OUT OF THE SAME DOCUMENT the port assertion reads, so the recipe states one fact about
    # one reading. The first version ran `config --services` a second time, which cannot disagree in
    # practice but made two readings of the same thing; and the one before that counted EVERY
    # two-space-indented key, which is not the service count. This walks only the `services:` mapping.
    #
    # Fourteen is a FLOOR, not the authoritative list: `tests/test_deploy_topology.py` crosses the
    # resolved set against a named table as an exact equality. This is here so the recipe cannot pass
    # on an empty read.
    services="$(printf '%s\n' "$resolved" | awk '
      /^services:/ { inside = 1; next }
      /^[a-zA-Z]/  { inside = 0 }
      inside && /^  [a-zA-Z0-9_-]+:$/ { count++ }
      END { print count + 0 }
    ')"
    if [ "$services" -lt 14 ]; then
      echo "the resolved stack has $services services, fewer than the 14 it declares: this read" >&2
      echo "something other than the deployed configuration" >&2
      exit 1
    fi
    if printf '%s' "$resolved" | grep -q 'published:'; then
      echo "a service in the deployed stack publishes a host port:" >&2
      printf '%s' "$resolved" | grep -B8 'published:' >&2
      exit 1
    fi
    echo "no host port is published by any of the $services resolved services in the deployed stack"

# Wait for the api to answer /readyz, which is what a deploy is gated on.
#
# Runs the SAME probe the container healthcheck runs, from inside the container, because that is the
# only place the api is reachable: no host port is published and the tunnel fronts the frontend.
# `urlopen` raises on the 503 /readyz answers while the database is unreachable or the migration head
# is not applied.
await-ready seconds="120":
    #!/usr/bin/env bash
    set -uo pipefail
    probe="import urllib.request as u; u.urlopen('http://127.0.0.1:8000/readyz', timeout=3)"
    deadline=$(( $(date +%s) + {{seconds}} ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
      if docker compose {{deploy_compose}} exec -T api python -c "$probe" >/dev/null 2>&1; then
        echo "/readyz answers 200: the applied revision is the head this checkout ships"
        exit 0
      fi
      sleep 3
    done
    echo "/readyz did not answer 200 within {{seconds}}s" >&2
    docker compose {{deploy_compose}} logs --tail 40 api >&2
    exit 1

# Deploy the digests in deployments/digests.env, and roll back to the previous ones on failure.
#
# The order is section 21's. Pull, migrate as a ONE-SHOT before anything starts, restart the three
# services that carry code, then WAIT FOR /readyz. Migrations never run at application startup, so two
# replicas cannot race, and `/readyz` compares the applied revision against the head this checkout
# ships, so a deploy that did not migrate cannot serve traffic.
#
# ROLLBACK IS RE-DEPLOYING THE PREVIOUS DIGESTS, which is why they are recorded. `digests.env` is what
# cd.yml writes; `digests.previous.env` is the last set that reached readiness, so it is written AFTER
# a deploy proves ready rather than before. The rollback pulls with `--policy missing`, because the
# host it runs on may be the one that cannot reach the registry. A schema rollback is a restore rather
# than a deploy, which is why migrations are forward-only and reviewed.
deploy:
    #!/usr/bin/env bash
    set -uo pipefail
    current=deployments/digests.env
    previous=deployments/digests.previous.env
    if [ ! -f "$current" ]; then
      echo "$current does not exist. cd.yml writes it, and a deploy never floats a tag." >&2
      exit 1
    fi
    deploy_from() {
      set -a
      # shellcheck disable=SC1090
      . "$1"
      set +a
      # `--policy missing` on a rollback, and this is the load-bearing difference between the two
      # calls: the state a bad deploy is most likely to leave is a host that cannot reach the
      # registry, and every previous image is already in the local store because a prior deploy
      # pulled it. A plain `pull` would fail the rollback at its first command, which contradicted
      # the rationale this whole arrangement is written from.
      docker compose {{deploy_compose}} pull --quiet --policy "$2" || return 1
      docker compose {{deploy_compose}} up -d postgres || return 1
      docker compose {{deploy_compose}} run --rm --no-deps api alembic upgrade head || return 1
      docker compose {{deploy_compose}} up -d --no-deps api worker frontend || return 1
      docker compose {{deploy_compose}} up -d cloudflared prometheus alertmanager grafana \
        node_exporter cadvisor postgres_exporter || return 1
      just await-ready
    }
    if deploy_from "$current" always; then
      cp "$current" "$previous"
      echo "deployed, ready, and recorded $previous as the release to roll back to"
      exit 0
    fi
    echo "the deploy did not reach readiness" >&2
    if [ ! -f "$previous" ]; then
      echo "and no previous release is recorded, so the stack is as the failed deploy left it." >&2
      echo "docs/runbooks/deploy-and-rollback.md is the procedure." >&2
      exit 1
    fi
    echo "re-deploying the previous digests from $previous" >&2
    if deploy_from "$previous" missing; then
      echo "rolled back to the previous release, which is ready" >&2
      exit 1
    fi
    echo "THE ROLLBACK ALSO FAILED, which is the case the runbook's last section covers." >&2
    exit 1

# --- Backup and recovery ----------------------------------------------------
# An untested backup is a belief. `just restore-drill` is the only thing here that proves otherwise.

# Put the release's recorded digests in the environment of a recipe that runs `docker compose`.
#
# THE ONE PLACE THE DIGEST FILE IS READ, and every recipe below interpolates this line rather than
# repeating it. `cd.yml` writes `deployments/digests.env` on the host and `just deploy` records the last
# set that reached readiness; compose interpolates those variables and the deploy overlay requires
# them, so without this every human invocation on the host would resolve a `:latest` tag that a digest
# pull never created and compose would build one from the checkout.
#
# A SOURCED LINE RATHER THAN A WRAPPER RECIPE, and that is a correction: the first version was a
# `_compose +ARGS` recipe, and `{{ARGS}}` interpolates a space-joined string into a shell, which
# re-word-splits it. A caller that took care to write `run --rm ops sh -c 'psql -c "..."'` lost the
# quoting one layer down. Sourcing keeps every caller's own quoting intact and still reads the file in
# one place.
#
# Absent locally, which is correct: `just drill-local` composes files that need no digest, and any
# other recipe run without them stops at compose's own message naming the variable.
read_digests := "set -a; [ -f deployments/digests.env ] && . deployments/digests.env; set +a"

# Take one backup now: the fingerprint, then the dump. Both steps, in that order.
#
# TWO CONTAINERS, and the order is the point. The fingerprint is the reading a restore is checked
# against and it needs the application, because the rotation cursor is a domain projection; the dump
# needs `pg_dump` from the pinned Postgres image. The dump step REFUSES a fingerprint older than half
# an hour, so a fingerprint step that failed cannot leave an earlier file to be uploaded beside a new
# dump.
#
# The first step is the one that makes the other two possible on a new deployment: a fresh named
# volume belongs to root and neither writer is root.
#
# The nightly timer runs this recipe rather than the two commands, so the schedule and a manual run
# cannot drift. See `deployments/systemd/syncr-backup.service`.
backup-now:
    #!/usr/bin/env bash
    set -uo pipefail
    {{read_digests}}
    docker compose {{ops_compose}} run --rm ops python3 -m ops.prepare || exit 1
    docker compose {{ops_compose}} run --rm fingerprint || exit 1
    docker compose {{ops_compose}} run --rm ops python3 -m ops.dump

# Ship every archived WAL segment off-host. Runs once a minute from a timer.
#
# Reads `pg_stat_archiver` FIRST and refuses when Postgres reports its own archive_command failing: a
# failing archiver leaves the staging volume empty, which is exactly what a healthy one leaves, so
# publishing a fresh timestamp for an empty directory would claim a five-minute recovery point while
# none existed.
wal-ship:
    #!/usr/bin/env bash
    set -uo pipefail
    {{read_digests}}
    docker compose {{ops_compose}} run --rm ops python3 -m ops.ship

# Cross the user ids the ops container chowns volumes to against what the images actually run as.
#
# The numbers are declared in `docker-compose.yml` and the images decide them, so this is the one
# check that keeps a base image renumbering its user from turning into a nightly backup that cannot
# write. Both are 999 today, which is the first system user a Debian base creates: a coincidence, and
# a coincidence is exactly what needs a check rather than a comment.
uid-check:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=0
    # `--profile ops`, because `docker compose config` omits a profile-gated service and the ops
    # service is where these are declared: without it this read returns nothing and compares nothing.
    #
    # THE BASE FILE, named explicitly rather than `ops_compose`: what this crosses is a DECLARATION
    # against the images two Dockerfiles produce, which is true of the checkout rather than of a
    # release, so it must be runnable on a machine that has no recorded digests.
    declared() {
      docker compose -f docker-compose.yml --profile ops config \
        | awk -v key="$1:" '$1 == key {gsub(/"/, "", $2); print $2; exit}'
    }
    check() {
      if [ "$2" != "$3" ]; then
        echo "$1 is declared as $2 and the image runs as $3" >&2
        failed=1
      else
        echo "$1 is $2, and the image agrees"
      fi
    }
    # The api image declares `USER syncr`, so its own `id -u` is what it runs as.
    check SYNCR_APP_UID "$(declared SYNCR_APP_UID)" \
      "$(docker run --rm --entrypoint id syncr-api:${SYNCR_IMAGE_TAG:-latest} -u)"
    # The Postgres image starts as root and drops to `postgres` through its entrypoint, so `id -u`
    # would report 0. `archive_command` runs as that user, which is what this asks for by name.
    check SYNCR_POSTGRES_UID "$(declared SYNCR_POSTGRES_UID)" \
      "$(docker run --rm --entrypoint id postgres:16.10-bookworm -u postgres)"
    exit "$failed"

# Run the nightly learning job as the scheduled one-shot, in the stack.
#
# `just learn` is the inner-loop equivalent and runs on the host against the dev database. This is what
# the timer runs: the container exits non-zero when a tenant's fit failed, and writes its exposition to
# the textfile collector before exiting, which is how `LearningJobFailed` can see a run at all.
learn-once:
    #!/usr/bin/env bash
    set -uo pipefail
    {{read_digests}}
    docker compose {{ops_compose}} --profile scheduled run --rm learning

# THE RESTORE DRILL. Restore the newest off-host backup into a clean database, boot the stack against
# it, and confirm the data came back.
#
# This recipe automates the mechanics; A HUMAN CONFIRMS THE OUTCOME. What it prints is a list of
# claims, each PASS or FAIL, because the pass condition is DATA READ BACK rather than an exit status:
# `pg_restore` exits 0 having restored an empty archive.
#
# It needs the PRIVATE half of the backup key, which lives off the host. That is deliberate, and
# proving the key can be used is half of what this drill is for: set SYNCR_BACKUP_PRIVATE_KEY to a
# path inside the secrets mount before running.
#
# Six steps. The scratch database is dropped at both ends, so nothing an earlier run left behind can
# satisfy this one:
#
#   1  fetch      download the newest dump and its fingerprint, decrypt both, verify the archive
#   2  scratch    a clean Postgres, its own volume, a different database name from production's
#   3  restore    refuse if the target IS production, refuse if it holds tables, then pg_restore
#   4  migrate    the one-shot a deploy runs, so the copy reaches the head this checkout ships
#   5  boot       the api against the copy, waiting for its own /readyz healthcheck
#   6  compare    the same fingerprint reader, against the manifest, inside the recovery objective
restore-drill:
    #!/usr/bin/env bash
    set -uo pipefail
    {{read_digests}}
    SYNCR_DRILL_STARTED_AT="$(date +%s)"
    export SYNCR_DRILL_STARTED_AT
    drill() { docker compose {{restore_compose}} "$@"; }
    # SURGICAL, BY SERVICE NAME. Never `down -v`: that is scoped to the PROJECT, and a local run
    # proved what that means here, deleting `pgdata`, the staging volume and the bucket. On the
    # deployed host the drill's own teardown would have destroyed the live database. The scratch
    # instance declares no volume, so removing its container removes its data with it.
    scratch() { drill rm -fsv postgres-restore api-restore >/dev/null 2>&1; }
    trap scratch EXIT
    echo "--- 1/6 fetching the newest backup and verifying the archive"
    drill run --rm ops python3 -m ops.fetch || exit 1
    echo "--- 2/6 starting a clean scratch database"
    scratch
    drill up -d --wait postgres-restore || exit 1
    echo "--- 3/6 restoring into it"
    drill run --rm ops python3 -m ops.restore || exit 1
    echo "--- 4/6 applying migrations as the one-shot a deploy runs"
    drill run --rm --no-deps api-restore alembic upgrade head || exit 1
    echo "--- 5/6 booting the api against the restored copy and waiting for /readyz"
    drill --profile ops up -d --wait api-restore || exit 1
    echo "--- 6/6 reading the restored copy back"
    drill run --rm fingerprint-restore || exit 1
    drill run --rm ops python3 -m ops.compare

# --- The drill, without a bucket --------------------------------------------
# DEVELOPMENT ONLY. An instrument nobody can run is an instrument nobody has run, and every guard in
# the backup path is written against a failure. These three recipes are how the whole path is
# exercised on a machine with no cloud account: the bucket becomes a local rclone remote and the keys
# become a throwaway pair. Nothing else changes.

# Generate the throwaway keypair the local drill encrypts to and decrypts with.
#
# In production the PRIVATE half is off the host entirely and a person brings it to a drill, which is
# what "a key held outside the VPS" means and what makes the copies useless to whoever reaches the
# host. Locally both halves sit in `deployments/secrets/`, which is gitignored, and neither has ever
# encrypted anything real.
drill-keys:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p deployments/secrets
    if [ -f deployments/secrets/drill-recipient.pub.asc ]; then
      echo "deployments/secrets already holds a drill keypair"
      exit 0
    fi
    home="$(mktemp -d)"
    trap 'rm -rf "$home"' EXIT
    gpg --homedir "$home" --batch --quick-generate-key \
      --passphrase '' 'syncr restore drill <drill@localhost>' default default never
    gpg --homedir "$home" --armor --export 'drill@localhost' \
      > deployments/secrets/drill-recipient.pub.asc
    gpg --homedir "$home" --armor --export-secret-keys 'drill@localhost' \
      > deployments/secrets/drill-recipient.key.asc
    chmod 600 deployments/secrets/drill-recipient.key.asc
    echo "wrote a throwaway keypair to deployments/secrets (gitignored)"

# Seed the local database with something a drill can lose.
#
# The seed is hand-written rows, and the drill's own evidence checks are what validate them: a binding
# spelled differently from the one the product writes would derive no cursor, and the verdict refuses
# a drill with no advanced cursor rather than reporting a pass. `deployments/drill/seed-local.sql` says
# so at the top.
#
# BASE FILE ONLY, deliberately. The dev overlay publishes 5432, and a host-local Postgres owning that
# port makes a compose route silently reach the wrong database: the most expensive hazard in this
# repository. Nothing here needs a host port, so nothing here publishes one.
#
# AND ON A DEPLOYED HOST THAT ROUTE IS THE LIVE DATABASE. `docker-compose.yml` declares the project
# `syncr`, which is the deployment's own, so this recipe would write invented rows into real plan
# history. So it carries the same refusal `just drill-local` does, as a dependency, for the reason
# stated where that refusal is declared.
drill-seed: _refuse-a-local-drill-on-a-deployed-host
    docker compose -f docker-compose.yml exec -T postgres \
      psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-syncr}" -d "${POSTGRES_DB:-syncr}" \
      -f /dev/stdin < deployments/drill/seed-local.sql

# REFUSE ON A DEPLOYED HOST, on EITHER of two facts a workstation does not have.
#
# Without this, running the local drill on a host would generate a THROWAWAY keypair, dump the LIVE
# database to that host's own disk encrypted to that key, restore into a locally-built image, and print
# "Every claim held. This backup restores, and the data came back." Every guard in the path would be
# satisfied and the drill would prove nothing about the real bucket or the real key. The standard
# here is that an instrument refuses rather than relying on its name, which is why `ops.restore`
# requires the live target instead of trusting its caller.
#
# TWO CALLERS, ONE REFUSAL. `just drill-seed` carries it as well, and its hazard is a different one:
# it writes invented rows into whatever `docker-compose.yml` resolves to, which on a host is the live
# database rather than a throwaway copy of one.
#
# TWO FACTS, BECAUSE ONE FILE GOING MISSING MUST NOT RE-ENABLE THE PATH:
#
#   deployments/digests.env                    the release `cd.yml` and `just deploy` recorded
#   deployments/secrets/backup-recipient.asc   the production public key, scp'd in step 5
#
# The first version keyed on the digest file alone, and that file was untracked and NOT gitignored, so
# any `git clean -fd` during troubleshooting removed it: after that `just restore-drill` aborted for
# want of digests AND this recipe stopped refusing, leaving the throwaway-key path as the only drill
# that still ran. The digest file is gitignored now, which puts it behind `git clean -x`, and the
# public key sits under `deployments/secrets/.gitignore`'s `*`, so the two do not go missing together.
#
# A DEPENDENCY RATHER THAN THE FIRST LINE OF THE BODY, and listed before `drill-keys`, because `just`
# runs dependencies left to right: the first version refused only after `drill-keys` had already
# written a throwaway keypair into `deployments/secrets` on the host it was refusing to run on.
[private]
_refuse-a-local-drill-on-a-deployed-host:
    #!/usr/bin/env bash
    set -uo pipefail
    for evidence in deployments/digests.env deployments/secrets/backup-recipient.asc; do
      [ -e "$evidence" ] || continue
      echo "this host is a deployment ($evidence exists): run \`just restore-drill\`, which uses the" >&2
      echo "real bucket and the real key. \`just drill-local\` proves the mechanics on a development" >&2
      echo "machine and nothing about this host: it would dump the live database under a throwaway" >&2
      echo "key." >&2
      echo "\`just drill-seed\` writes invented rows into that same live database, which is the" >&2
      echo "project \`docker-compose.yml\` resolves to." >&2
      exit 1
    done

# The whole path, locally and from nothing: a database, migrations, seed, a real backup into the local
# bucket, then the real drill against it.
#
# Self-contained on purpose. The first version of a probe recipe in this repository was unrunnable
# three times over, and each time running it was what revealed that.
drill-local: _refuse-a-local-drill-on-a-deployed-host drill-keys
    #!/usr/bin/env bash
    set -uo pipefail
    # THE DEVELOPMENT ENCRYPTION KEY, exported here rather than worked around in the compose files.
    #
    # `docker-compose.yml` interpolates `${GOOGLE_TOKEN_ENCRYPTION_KEY:-}`, and an empty value
    # OVERRIDES the settings layer's own safe development default, so the api refuses to start by
    # name: measured, on a checkout with no `.env` at all. That refusal is the guard working, and it
    # must stay for production, where a Fernet key from this repository would be a stored refresh
    # token in the clear. So the value comes from `.env.example`, where it is documented as the
    # development default, and it is exported for this recipe only.
    export GOOGLE_TOKEN_ENCRYPTION_KEY="${GOOGLE_TOKEN_ENCRYPTION_KEY:-ZGV2LW9ubHktZ29vZ2xlLXRva2VuLWVuY3J5cHQta2U=}"
    # TWO overlay sets, and the difference matters: the backup runs against the LIVE database and the
    # drill runs against the scratch one. `docker-compose.restore.yml` is what repoints the ops
    # container at the scratch instance, so composing it into the backup would take a dump of a
    # database that is not running. Neither set carries the deploy overlay, which is what lets both
    # resolve a local tag on a machine that has never deployed.
    backup_overlays="-f docker-compose.yml -f docker-compose.drill-local.yml"
    drill_overlays="-f docker-compose.yml -f docker-compose.restore.yml -f docker-compose.drill-local.yml"
    echo "=== 1 a database, with no host port published"
    docker compose -f docker-compose.yml up -d --wait postgres || exit 1
    echo "=== 2 migrations, as the one-shot a deploy runs"
    docker compose -f docker-compose.yml run --rm --no-deps api alembic upgrade head || exit 1
    echo "=== 3 seeding something the drill can lose"
    # THE APPLICATION, NOT THE SERVICE. Step 1 brings up postgres only, so the seeder runs as a
    # one-shot in the api's image, exactly the way the migration one-shot above does. It writes
    # every row through the product's own repositories and services and refuses any database that
    # holds a tenant it did not create itself.
    docker compose -f docker-compose.yml run --rm --no-deps api syncr-drill-seed || exit 1
    echo "=== 4 a real backup into the local bucket"
    SYNCR_OPS_COMPOSE="$backup_overlays" just backup-now || exit 1
    echo "=== 5 the drill, against what is in that bucket"
    SYNCR_RESTORE_COMPOSE="$drill_overlays" just restore-drill

# --- Point-in-time recovery, rehearsed locally -------------------------------

# THE POINT-IN-TIME REHEARSAL. Recover a scratch instance to an instant ASKED FOR after the dump,
# from a physical base backup plus the archived WAL, against the local bucket and the throwaway
# keypair.
#
# WHAT SEPARATES THIS FROM `just restore-drill`. That drill restores the nightly dump, and a dump
# lands at THE INSTANT IT WAS TAKEN whatever anyone asks for: `pg_restore` replays nothing. This
# rehearsal takes a physical base backup (`pg_basebackup`), writes a row AFTER it, and recovers to
# an instant past that row. Only real WAL replay can put the row back, and only an honored
# `recovery_target_time` could have stopped before it.
#
# THE NINTH CLAIM, beside the eight `ops.compare` prints about the recovered copy: the database
# came back at the instant ASKED FOR rather than at the instant of the dump (`ops.pitr`). It is
# shown to fail where a fake recovery hides, by recovering a SECOND time to the DUMP'S OWN instant:
# there the post-dump row must be ABSENT. Present at both instants means the replay ignored the
# target; absent at both means nothing replayed and this was a dump restore all along. Either way
# the rehearsal fails loudly rather than reporting a pass.
#
# THE BASE BACKUP DOES NOT TRANSIT THE BUCKET, deliberately: it is streamed from the live instance
# into the scratch volume moments before it is used. The direction under test here is REPLAY; the
# dump-to-bucket-to-fetch direction is what `just restore-drill` already proves. The WAL does
# transit the bucket, encrypted to the throwaway key, and comes back the way a real recovery reads
# it: one segment per `python3 -m ops.fetch_segment` invocation.
#
# WHY NOTHING HERE IS ON CI, stated here rather than left as an omission: the suite gates every
# structure this recipe depends on (`tests/test_pitr_drill.py` carries the refusals, the crossings
# and the claim logic), and what CI cannot host is the run itself. Docker builds, a wall-clock WAL
# timeline with sleeps in it, and minutes of runtime to prove what no unit test can fake. So the
# structure is gated and the behavior is rehearsed by hand, exactly like `just drill-local`.
drill-pitr-local: _refuse-a-local-drill-on-a-deployed-host drill-keys
    #!/usr/bin/env bash
    set -uo pipefail
    # The same development encryption key `just drill-local` exports, for the reason stated there:
    # an empty value overrides the settings layer's safe development default and the api refuses
    # to start by name.
    export GOOGLE_TOKEN_ENCRYPTION_KEY="${GOOGLE_TOKEN_ENCRYPTION_KEY:-ZGV2LW9ubHktZ29vZ2xlLXRva2VuLWVuY3J5cHQta2U=}"
    export SYNCR_DRILL_STARTED_AT="$(date +%s)"
    backup_overlays="-f docker-compose.yml -f docker-compose.drill-local.yml"
    pitr_overlays="-f docker-compose.yml -f docker-compose.restore.yml -f docker-compose.drill-local.yml -f docker-compose.drill-pitr.yml"
    live() { docker compose -f docker-compose.yml "$@"; }
    backup() { docker compose $backup_overlays "$@"; }
    pitr() { docker compose $pitr_overlays "$@"; }
    psql_live() {
      live exec -T postgres psql -v ON_ERROR_STOP=1 \
        -U "${POSTGRES_USER:-syncr}" -d "${POSTGRES_DB:-syncr}" "$@"
    }
    # The one row whose presence IS the ninth claim: written after the base backup, so a copy that
    # came back at the dump's instant cannot hold it.
    marker() {
      pitr exec -T postgres-recovery psql -tA \
        -U "${POSTGRES_USER:-syncr}" -d "${POSTGRES_DB:-syncr}" \
        -c "select count(*) from public.edit_events where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'"
    }
    # Millisecond precision, taken INSIDE the ops image because the host's `date` may be BSD's,
    # whose %N answers literally. Postgres parses this format as a `recovery_target_time`.
    instant() { backup run --rm --no-deps ops date -u '+%Y-%m-%d %H:%M:%S.%N' | cut -b1-23; }
    # The volume's PHYSICAL name follows the resolved project, which an environment override moves:
    # derive it rather than spell it, so the removal below cannot quietly remove nothing.
    pitr_volume() {
      pitr config --format json \
        | python3 -c 'import json, sys; print(json.load(sys.stdin)["name"] + "_pitr_pgdata")'
    }
    await_promotion() {
      for _ in $(seq 1 90); do
        [ "$(pitr exec -T postgres-recovery psql -tA \
          -U "${POSTGRES_USER:-syncr}" -d "${POSTGRES_DB:-syncr}" \
          -c 'select pg_is_in_recovery()' 2>/dev/null)" = "f" ] && return 0
        sleep 2
      done
      echo "the recovery did not reach its target within three minutes" >&2
      return 1
    }
    # BY SERVICE NAME AND BY VOLUME NAME, never a project-scoped teardown: this
    # project is `syncr`, and on a deployed host that project holds the live database's volume.
    teardown() {
      pitr rm -fsv postgres-recovery >/dev/null 2>&1
      docker volume rm -f "$(pitr_volume)" >/dev/null 2>&1
    }
    trap teardown EXIT

    echo "--- 1/8 a database, migrations, and evidence"
    live up -d --wait postgres || exit 1
    live run --rm --no-deps api alembic upgrade head || exit 1
    just drill-seed || exit 1
    # REFUSE OVER AN EMPTY EVIDENCE SET, as `just restore-drill` refuses through the verdict's
    # `_there_was_data_to_lose`: a recovery of an empty table always succeeds, so a rehearsal over
    # empty evidence tables is the most convincing false pass there is. The five names are crossed
    # against `ops.config.EVIDENCE_TABLES` by a test, so the two cannot drift apart silently.
    for table in public.plan_revisions public.block_outcomes public.pins public.week_adjustments public.edit_events; do
      # A FAILED READ is not an EMPTY TABLE: refuse by name rather than letting the empty answer
      # pose as a zero and name the wrong refusal.
      count="$(psql_live -tAc "select count(*) from $table")" \
        || { echo "could not read the row count of $table" >&2; exit 1; }
      if [ "${count:-0}" -eq 0 ]; then
        echo "$table held no rows before the base backup, so this rehearsal proves nothing" >&2
        echo "about it. Seed the database and re-run." >&2
        exit 1
      fi
    done
    # Establishes the volumes' ownership before anything but root writes to them: what
    # `just backup-now` does as its own first step every night.
    backup run --rm --no-deps ops python3 -m ops.prepare || exit 1
    # A REPLICATION CONNECTION FOR THE BASE BACKUP. The initialized pg_hba.conf admits regular
    # connections from any host and no replication connection, which is exactly what
    # `pg_basebackup --wal-method=stream` asks for: measured, on this checkout. Idempotent, and
    # password-authenticated like every other host line, so nothing new trusts the drill network.
    live exec -T postgres sh -c \
      'grep -q "host replication" "$PGDATA/pg_hba.conf" || echo "host replication all all scram-sha-256" >> "$PGDATA/pg_hba.conf"' || exit 1
    psql_live -c 'select pg_reload_conf()' >/dev/null || exit 1

    echo "--- 2/8 shipping what the seed wrote"
    psql_live -c 'select pg_switch_wal()' >/dev/null || exit 1
    SYNCR_OPS_COMPOSE="$backup_overlays" just wal-ship || exit 1

    # THE REHEARSAL'S ROWS, CLEARED BEFORE THE BASE BACKUP. Both markers are deleted HERE and not
    # beside their inserts, because the live database outlives one run: a marker a previous run
    # left behind would be captured INTO this run's base backup, sit in every recovery at any
    # instant, and make the control below see the marker where by construction it cannot be.
    psql_live -c "delete from public.edit_events where id in ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc')" || exit 1

    echo "--- 3/8 the physical base backup, streamed into the scratch volume"
    backup run --rm --no-deps ops sh -c \
      'rm -rf /var/backups/restore/base && mkdir /var/backups/restore/base' || exit 1
    backup run --rm --no-deps ops pg_basebackup --pgdata=/var/backups/restore/base \
      --format=plain --wal-method=stream --checkpoint=fast || exit 1
    dump_instant="$(instant)"

    echo "--- 4/8 a row written AFTER the dump, then its WAL shipped"
    # The dump instant must be strictly BEFORE this commit, at any clock or truncation: the sleep
    # is what keeps the control recovery below from including the marker at equal resolution.
    sleep 2
    psql_live -c "insert into public.edit_events (id, tenant_id, iso_week, binding, proposed_starts_at, proposed_ends_at, accepted_starts_at, accepted_ends_at, objective_delta, context, weight_set_version, created_at) values ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '11111111-1111-4111-8111-111111111111', '2026-W32', '{\"kind\": \"habit\", \"entity_id\": \"44444444-4444-4444-8444-444444444444\", \"occurrence_key\": \"09\", \"split_index\": null}'::jsonb, now(), now() + interval '1 hour', now() + interval '2 hours', now() + interval '3 hours', 0.5, '{\"note\": \"written after the base backup: the instant the rehearsal asks for\"}'::jsonb, 1, now())" || exit 1
    asked_for="$(instant)"
    # ONE MORE TRANSACTION, COMMITTED PAST THE INSTANT ASKED FOR, and deleted again before the
    # manifest below is read. Not decoration: a recovery reaches its target by finding a COMMIT
    # stamped after it, so an archive whose last commit precedes the target does not stop there,
    # it FAILS -- Postgres cannot know no further transaction follows. Measured, on this checkout:
    # shipping an empty switched-out segment changed nothing, because an empty segment carries no
    # commit. The delete makes the live database's own contents identical either side of the
    # instant, so the EIGHT claims still hold against the copy recovered to the target.
    psql_live -c "insert into public.edit_events (id, tenant_id, iso_week, binding, proposed_starts_at, proposed_ends_at, accepted_starts_at, accepted_ends_at, objective_delta, context, weight_set_version, created_at) values ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', '11111111-1111-4111-8111-111111111111', '2026-W32', '{\"kind\": \"habit\", \"entity_id\": \"44444444-4444-4444-8444-444444444444\", \"occurrence_key\": \"10\", \"split_index\": null}'::jsonb, now(), now() + interval '1 hour', now() + interval '2 hours', now() + interval '3 hours', 0.5, '{\"note\": \"committed past the target so the target is reachable\"}'::jsonb, 1, now())" || exit 1
    psql_live -c "delete from public.edit_events where id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'" || exit 1
    psql_live -c 'select pg_switch_wal()' >/dev/null || exit 1
    SYNCR_OPS_COMPOSE="$backup_overlays" just wal-ship || exit 1

    echo "--- 5/8 staging every segment the bucket holds"
    objects="$(backup run --rm --no-deps ops sh -c 'rclone lsf --recursive "$SYNCR_BACKUP_REMOTE/wal"')" || exit 1
    if [ -z "$objects" ]; then
      echo "the bucket holds no archived WAL segment, so there is nothing a recovery could" >&2
      echo "replay and nothing this rehearsal could prove. Ship and re-run." >&2
      exit 1
    fi
    for object in $objects; do
      case "$object" in *.gz.gpg) ;; *) continue ;; esac
      segment="${object%.gz.gpg}"
      printf '%s' "$segment" \
        | grep -q -E '^([0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?|[0-9A-F]{8}\.history)$' || continue
      pitr run --rm --no-deps ops python3 -m ops.fetch_segment "$segment" || exit 1
    done

    echo "--- 6/8 recovering to the instant ASKED FOR ($asked_for)"
    export SYNCR_PITR_TARGET_TIME="$asked_for"
    teardown
    pitr run --rm --no-deps pitr-prepare || exit 1
    pitr up -d --force-recreate --no-deps postgres-recovery || exit 1
    await_promotion || exit 1
    found_at_target="$(marker)"
    # The reading the EIGHT claims are judged on. Both readings are written by the same console
    # script the drill uses, pointed at two databases and one scratch directory; the staging volume
    # is no use for this, because a directory that exists in an image resets a mounted empty
    # volume's ownership at every container creation here, which is what a reading into it kept
    # failing on. The scratch directory is non-empty from the base backup onward and keeps what
    # `ops.prepare` gave it.
    pitr run --rm --no-deps ops python3 -c \
      "import os; from ops import environment; from ops.prepare import writable_by_app; writable_by_app(environment.paths(os.environ).scratch, environ=os.environ)" || exit 1
    pitr run --rm --no-deps \
      -e "DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER:-syncr}:${POSTGRES_PASSWORD:-syncr}@postgres:5432/${POSTGRES_DB:-syncr}" \
      -e SYNCR_FINGERPRINT_PATH=/var/backups/restore/restore.manifest.json \
      fingerprint-restore || exit 1
    pitr run --rm --no-deps \
      -e "DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER:-syncr}:${POSTGRES_PASSWORD:-syncr}@postgres-recovery:5432/${POSTGRES_DB:-syncr}" \
      fingerprint-restore || exit 1
    pitr run --rm --no-deps ops python3 -m ops.compare || exit 1

    echo "--- 7/8 recovering AGAIN, to the dump's own instant ($dump_instant)"
    teardown
    export SYNCR_PITR_TARGET_TIME="$dump_instant"
    pitr run --rm --no-deps pitr-prepare || exit 1
    pitr up -d --force-recreate --no-deps postgres-recovery || exit 1
    await_promotion || exit 1
    found_at_dump_instant="$(marker)"
    # A COUNT THAT IS NOT A NUMBER means the query above failed, not that the row is absent:
    # refuse by name here rather than letting ops.pitr answer with its usage text.
    for counted in "$found_at_target" "$found_at_dump_instant"; do
      case "$counted" in '' | *[!0-9]*)
        echo "the rehearsal could not read one of its own marker counts" >&2
        exit 1
        ;;
      esac
    done

    echo "--- 8/8 the ninth claim"
    pitr run --rm --no-deps ops python3 -m ops.pitr \
      "$asked_for" "$dump_instant" "$found_at_target" "$found_at_dump_instant" || exit 1
