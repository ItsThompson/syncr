# syntax=docker/dockerfile:1

# =============================================================================
# The syncr-api image. Two entrypoints, one image: `syncr-api` serves HTTP and
# `syncr-worker` runs the duty loop. They need the same repositories, the same ORM
# session handling, and the same settings, so splitting them would duplicate
# persistence or invert the dependency.
#
# THE LOAD-BEARING PART. uv resolves ONE shared environment for the workspace, so a
# plain `uv sync --package syncr-api` would install EVERY member and put scipy in
# this image the moment the learning fitters land. Instead the builder exports the
# lean locked third-party set for syncr-api alone, then editable-installs only the
# four members this image is allowed to carry. A CI job asserts the result by
# importing scipy in here and requiring it to fail.
#
# Built from the REPO-ROOT context, because the resolve step needs the workspace
# root, the lockfile, and every member's pyproject to load the workspace graph.
# =============================================================================

FROM python:3.12-slim-bookworm AS builder

# Pinned; review together with the base image.
COPY --from=ghcr.io/astral-sh/uv:0.11.20 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Resolve layer. Every member's pyproject must be present for uv to load the
# workspace graph and resolve the `{ workspace = true }` sources, but only their
# metadata lands here, so this layer stays cached across source-only changes.
COPY pyproject.toml uv.lock ./
COPY packages/syncr-common/pyproject.toml packages/syncr-common/pyproject.toml
COPY packages/syncr-domain/pyproject.toml packages/syncr-domain/pyproject.toml
COPY packages/syncr-solver/pyproject.toml packages/syncr-solver/pyproject.toml
COPY packages/syncr-api/pyproject.toml packages/syncr-api/pyproject.toml
COPY packages/syncr-learning/pyproject.toml packages/syncr-learning/pyproject.toml
COPY cli/pyproject.toml cli/pyproject.toml

# Export the locked third-party set for syncr-api only, excluding the workspace
# members themselves, and install it. Dependency-only cached layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-emit-workspace --package syncr-api \
      --output-file /tmp/requirements.txt \
    && uv venv "$VIRTUAL_ENV" \
    && uv pip install --requirement /tmp/requirements.txt

# Build layer. Only the four permitted members are copied at all, so neither
# syncr-learning nor the cli can reach this image even by accident. Editable so the
# dev overlay's bind mount plus autoreload picks up an edit without a rebuild.
COPY packages/syncr-common/ packages/syncr-common/
COPY packages/syncr-domain/ packages/syncr-domain/
COPY packages/syncr-solver/ packages/syncr-solver/
COPY packages/syncr-api/ packages/syncr-api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-deps \
      --editable ./packages/syncr-common \
      --editable ./packages/syncr-domain \
      --editable ./packages/syncr-solver \
      --editable ./packages/syncr-api

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# The application never needs root.
RUN groupadd --system syncr && useradd --system --gid syncr --home-dir /app syncr

# alembic.ini resolves from here, so `docker compose run --rm api alembic upgrade
# head` is the migration one-shot with no extra arguments.
WORKDIR /app/packages/syncr-api

COPY --from=builder --chown=syncr:syncr /app/.venv /app/.venv
COPY --from=builder --chown=syncr:syncr /app/packages /app/packages

# The venv console scripts and interpreter on PATH: syncr-api, syncr-worker,
# uvicorn, alembic, and the python that backs the Compose healthcheck.
ENV PATH="/app/.venv/bin:$PATH"

USER syncr
EXPOSE 8000
CMD ["syncr-api"]
