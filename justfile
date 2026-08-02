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
    lefthook install

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

# Every backend suite
test:
    #!/usr/bin/env bash
    set -euo pipefail
    for member in {{members}}; do
      echo "--- $member"
      (cd "$member" && uv run --no-sync pytest)
    done

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

# Every static gate over every member: ruff, the format check, and mypy
lint: lint-style typecheck

# ruff check plus the format check over every member
lint-style:
    #!/usr/bin/env bash
    set -euo pipefail
    for member in {{members}}; do
      echo "--- $member"
      (cd "$member" && uv run --no-sync ruff check . && uv run --no-sync ruff format --check .)
    done

# mypy over every member. The pre-push hook runs this
typecheck:
    #!/usr/bin/env bash
    set -euo pipefail
    for member in {{members}}; do
      echo "--- $member"
      (cd "$member" && uv run --no-sync mypy)
    done

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

# Assert the api image cannot import scipy, which is the zero-ML rule at runtime
image-boundary:
    docker build -f packages/syncr-api/Dockerfile -t syncr-api:boundary-check .
    ! docker run --rm --entrypoint python syncr-api:boundary-check -c "import scipy"
    @echo "image boundary holds: scipy is not importable in the api image"
