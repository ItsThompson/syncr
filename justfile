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

# The api only, on the host, with autoreload. Needs `just dev-infra` and `just migrate`
dev-api:
    cd packages/syncr-api && uv run --no-sync uvicorn syncr_api.api.main:app \
      --host 127.0.0.1 --port 8000 --reload

# The worker only, on the host. Needs `just dev-infra` and `just migrate`
dev-worker:
    cd packages/syncr-api && uv run --no-sync syncr-worker

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

# The offline learning suite
test-learning:
    cd packages/syncr-learning && uv run --no-sync pytest

# The CLI suite
test-cli:
    cd cli && uv run --no-sync pytest

# The frontend unit suite, with coverage. The pre-push hook runs this
test-frontend:
    cd frontend && npm run test:coverage

# --- Lint and format --------------------------------------------------------

# Every static gate: ruff, the format check, mypy, and the hook config
lint: lint-style typecheck lint-hooks

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
# Seven checks, none of which the others can cover:
#   oxlint          the language and React rules, plus the kit's import zones by SPECIFIER
#   stylelint       the design rules that live in CSS: no raw color, no motion, no radius
#   prettier        formatting, so twenty tickets of TypeScript accumulate no drift
#   tokens-validate the token layer, the sheets that render from it, and the theme that reads it
#   lint-markup     the design rules that reach the DOM as a class name or a data attribute
#   check-channels  each state channel assigned in exactly one file under the kit
#   check-imports   the kit's import zones again, by RESOLVED DIRECTORY rather than by specifier
#
# The last two overlap deliberately. oxlint matches a specifier's spelling, and three holes reached
# review that way: a barrel it did not name, a `.ts` extension, a `.js` extension resolving to a
# `.ts` file. check-imports resolves each import against the filesystem and asks which directory the
# file actually lives in, so a spelling nobody anticipated cannot slip past. Two checks, two
# different inputs, one rule.
#
# Every check runs even when an earlier one fails: one red linter must not hide the rest.
lint-frontend:
    #!/usr/bin/env bash
    set -uo pipefail
    cd frontend
    failed=0
    for check in lint:js lint:css lint:format lint:tokens lint:markup lint:channels lint:imports; do
      echo "--- $check"
      npm run --silent "$check" || failed=1
    done
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
