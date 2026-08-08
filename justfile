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

# Tear the dev stack down AND drop its volumes, for a fresh Postgres
dev-reset:
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
# The second check is the one worth having: `docs/smoke-scenarios.md` is the map from section 22's
# done-criteria table to something that can fail, and a row claiming an assertion no file makes is a list
# disagreeing with the fact it copies. It reads every column it is meant to bound, in both directions, and
# takes its titles from `playwright test --list` rather than from a regex over the source, because a regex
# counted a commented-out case as coverage.
#
# Every check runs even when an earlier one fails: one red linter must not hide the rest. Same shape as
# `lint-style`, comment included, so the pattern is recognisable as the same one.
lint-e2e:
    #!/usr/bin/env bash
    set -uo pipefail
    cd e2e
    failed=0
    for check in lint:format lint:scenarios; do
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
e2e-down:
    docker compose {{e2e_compose}} down -v

# The whole suite. Every scenario names its scenario number in its title
e2e:
    cd e2e && npx playwright test

# One scenario or one file, by title or path: `just e2e-only S10`
e2e-only pattern:
    cd e2e && npx playwright test {{pattern}}

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

# Outcomes recorded on every block the horizon's weeks have ended. Prints what it reached, and names the
# one refusal it tolerates: a solve of the current week is refused permanently, which is ticket 1570
seed-maturity-corpus:
    node e2e/src/seed/cli.ts maturity_corpus

# A week whose declared floors sit just inside its remaining capacity, which is what makes a floor
# reservation observable at all: 1470 discretionary minutes against 960 minutes of floor
seed-tight-capacity:
    node e2e/src/seed/cli.ts tight_capacity

# Tick the plan-horizon maintainer once, now. S1's "or trigger it": the wait is fifteen minutes,
# because the runner's first tick only sets its own due time
e2e-tick:
    docker compose {{e2e_compose}} run --rm --no-deps worker python /harness/tick.py

# --- Lint and format --------------------------------------------------------

# Every static gate: ruff, the format check, mypy, the deployment's own package, and the hook config
lint: lint-style typecheck lint-ops lint-hooks

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
# Nine checks, none of which the others can cover:
#   oxlint          the language and React rules, plus the kit's import zones by SPECIFIER
#   stylelint       the design rules that live in CSS: no raw color, no motion, no radius
#   prettier        formatting, so twenty tickets of TypeScript accumulate no drift
#   tokens-validate the token layer, the sheets that render from it, and the theme that reads it
#   lint-markup     the design rules that reach the DOM as a class name or a data attribute
#   check-channels  each state channel assigned in exactly one file under the kit
#   check-imports   the kit's import zones again, by RESOLVED DIRECTORY rather than by specifier
#   check-bundle    the built stylesheet, declaration by declaration, read with postcss
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
# THE NINTH READS A COMPOSED RESULT, which is the one input none of the other eight has. Every one of
# them reads a declaration, a class list, an attribute or the built text, and all three real defects on
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
# written. Ten seconds a commit is the price of the input none of the other eight has.
#
# THE RECIPE COUNTS ITS OWN CHECKS AND SAYS SO AT THE END, and that is not decoration. Six of the nine print
# `ok` themselves and three are third-party tools with their own success lines, so a reader counting `ok`
# counted six of nine, and a check that had silently stopped running looked exactly like the three that never
# said it. The tail line names how many ran, which is the figure the eight-of-nine loop this recipe already
# paid for would have contradicted.
#
# Every check runs even when an earlier one fails: one red linter must not hide the rest.
lint-frontend:
    #!/usr/bin/env bash
    set -uo pipefail
    cd frontend
    failed=0
    ran=0
    for check in lint:js lint:css lint:format lint:tokens lint:markup lint:channels lint:imports lint:bundle lint:render; do
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
drill-seed:
    docker compose -f docker-compose.yml exec -T postgres \
      psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-syncr}" -d "${POSTGRES_DB:-syncr}" \
      -f /dev/stdin < deployments/drill/seed-local.sql

# REFUSE ON A DEPLOYED HOST, on EITHER of two facts a workstation does not have.
#
# Without this, running the local drill on a host would generate a THROWAWAY keypair, dump the LIVE
# database to that host's own disk encrypted to that key, restore into a locally-built image, and print
# "Every claim held. This backup restores, and the data came back." Every guard in the path would be
# satisfied and the drill would prove nothing about the real bucket or the real key. This ticket's
# standard is that an instrument refuses rather than relying on its name, which is why `ops.restore`
# requires the live target instead of trusting its caller.
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
    just drill-seed || exit 1
    echo "=== 4 a real backup into the local bucket"
    SYNCR_OPS_COMPOSE="$backup_overlays" just backup-now || exit 1
    echo "=== 5 the drill, against what is in that bucket"
    SYNCR_RESTORE_COMPOSE="$drill_overlays" just restore-drill
