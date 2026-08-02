# syntax=docker/dockerfile:1

# =============================================================================
# The syncr-learning image. A SCHEDULED ONE-SHOT, not a service: scipy plus
# scikit-learn resident is roughly 800 MB for a job that runs nightly, which is 10%
# of an 8 GB host held permanently for a process idle 99.9% of the time.
#
# It installs common, domain, and learning, and nothing else. No FastAPI and no web
# stack: syncr-common's fastapi dependency sits behind an `http` extra this member
# does not request, so a one-shot job carries no server it will never listen on.
#
# Same export-then-install pattern as the api image, for the same reason: uv
# resolves one shared environment, so a plain `uv sync --package syncr-learning`
# would install every member.
# =============================================================================

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.20 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/syncr-common/pyproject.toml packages/syncr-common/pyproject.toml
COPY packages/syncr-domain/pyproject.toml packages/syncr-domain/pyproject.toml
COPY packages/syncr-solver/pyproject.toml packages/syncr-solver/pyproject.toml
COPY packages/syncr-api/pyproject.toml packages/syncr-api/pyproject.toml
COPY packages/syncr-learning/pyproject.toml packages/syncr-learning/pyproject.toml
COPY cli/pyproject.toml cli/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-emit-workspace --package syncr-learning \
      --output-file /tmp/requirements.txt \
    && uv venv "$VIRTUAL_ENV" \
    && uv pip install --requirement /tmp/requirements.txt

COPY packages/syncr-common/ packages/syncr-common/
COPY packages/syncr-domain/ packages/syncr-domain/
COPY packages/syncr-learning/ packages/syncr-learning/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-deps \
      --editable ./packages/syncr-common \
      --editable ./packages/syncr-domain \
      --editable ./packages/syncr-learning

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

RUN groupadd --system syncr && useradd --system --gid syncr --home-dir /app syncr

WORKDIR /app/packages/syncr-learning

COPY --from=builder --chown=syncr:syncr /app/.venv /app/.venv
COPY --from=builder --chown=syncr:syncr /app/packages /app/packages

ENV PATH="/app/.venv/bin:$PATH"

USER syncr
# The nightly job entrypoint lands with the fitters. Until then the image exists so
# the boundary it enforces is testable from the first commit.
CMD ["python", "-c", "import syncr_learning; print('syncr-learning image ready')"]
