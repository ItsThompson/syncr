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

# Build the shared root venv from the single root lockfile and install the hooks
setup:
    uv sync --all-packages
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

# The full dev stack: Postgres, the api with autoreload, and the worker
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

# --- Security ---------------------------------------------------------------

# The audit gate fails on ANY advisory rather than only on high severity. `uv audit`
# has no severity threshold, and its JSON schema is explicitly preview and may
# change, so parsing a severity out of it would be a gate that silently stops
# working. Failing on any advisory is strictly stronger and cannot rot. Suppress a
# specific finding by adding `--ignore <ID>` below with a comment saying why.

# Scan the locked dependency graph for known advisories
audit:
    uv audit --preview-features audit-command

# The scan the pre-commit hook runs on staged files, over the whole tree
secret-scan:
    git ls-files -z | xargs -0 uv run --no-sync detect-secrets-hook --baseline .secrets.baseline

# Re-baseline a reviewed finding. Run this, confirm every new entry is genuinely
# not a secret, then commit the baseline with the change that introduced it.
secret-baseline:
    uv run --no-sync detect-secrets scan --baseline .secrets.baseline --exclude-files '^\.venv/'
    @echo "review the new entries in .secrets.baseline before committing"

# Assert the zero-ML rule at runtime: the api image must import its own stack and
# must NOT be able to import scipy. The control comes first, because a bare negative
# assertion reads any non-zero exit as a held boundary, including a container that
# never started.
image-boundary:
    #!/usr/bin/env bash
    set -euo pipefail
    docker build -f packages/syncr-api/Dockerfile -t syncr-api:boundary-check .
    docker run --rm --entrypoint python syncr-api:boundary-check \
      -c "import fastapi, sqlalchemy, syncr_api, syncr_solver, syncr_domain, syncr_common"
    if docker run --rm --entrypoint python syncr-api:boundary-check -c "import scipy"; then
      echo "scipy is importable in the api image: the zero-ML boundary is broken" >&2
      exit 1
    fi
    docker build -f packages/syncr-learning/Dockerfile -t syncr-learning:boundary-check .
    docker run --rm syncr-learning:boundary-check \
      python -c "import syncr_learning, syncr_domain, syncr_common"
    if docker run --rm syncr-learning:boundary-check python -c "import fastapi"; then
      echo "fastapi is importable in the learning image: the offline boundary is broken" >&2
      exit 1
    fi
    echo "both image boundaries hold, and both images run"
