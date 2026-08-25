# syncr

syncr is a scheduling and life-management system that owns the plan. It turns long-term time
allocations and a short-term task backlog into a timeblocked week, projects that week onto the
user's calendar, and adapts the plan as reality diverges, without rearranging it behind the
user's back.

## Repository members

| Member | Responsibility |
|---|---|
| `packages/syncr-common` | Shared infrastructure: logging, metrics, health, settings. No domain knowledge. |
| `packages/syncr-domain` | Pure domain: entities, invariants, arithmetic. No I/O. |
| `packages/syncr-solver` | Placement: solve inputs to a plan document with reasons. Zero ML dependencies. |
| `packages/syncr-api` | FastAPI application, persistence, calendar adapters, and the worker entrypoint. |
| `packages/syncr-learning` | Offline feature extraction and parameter fitting, run as a nightly one-shot. The only member that may depend on scipy or scikit-learn. |
| `frontend/` | React SPA over the API, built with Vite and typed from the committed OpenAPI document. |
| `cli/` | Command-line OAuth client of the same API the browser uses. |
| `e2e/` | Playwright end-to-end suite, run against its own compose stack. |

## Setup

One-time:

```sh
just setup
```

This builds one shared root virtual environment from the single root `uv.lock`, installs every
Python member into it, installs the frontend's locked dependency tree, and installs the git
hooks. Every Python member's tools run against this one venv; there is no per-member environment
to create or sync.

## Development

The task runner is [just](https://github.com/casey/just). Run:

```sh
just --list
```

for the full recipe catalog: dev stack, migrations, per-member test and lint recipes, fixtures,
the e2e harness, deployment, and drills. Each recipe's header comment in the `justfile` says what
it does and what it needs; run a member's tests and lint through those recipes rather than by
hand, so ordering and flags stay in one place.
