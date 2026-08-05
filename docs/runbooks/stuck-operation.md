# An operation stuck `running`

## Trigger

An operation shows `running` and does not change. Either of these is how you find out:

- `GET /api/v1/operations?status=running` returns a row whose `startedAt` is minutes old.
- The Week screen reads `solving` and stays there.

Nothing pages for this on its own. A stuck operation resolves itself within the lease, and the
alerts that would fire are `SolveFailing` if the retries then fail, and `HorizonNotMaintained` if the
week in question was one the plan horizon maintainer was bringing into range. The latter watches
`syncr_horizon_weeks_without_plan`, which is exported today.

## What it means

An operation is `running` because a worker claimed it. If the worker then stopped -- killed, OOMed,
redeployed mid-solve -- the row stays `running` and nothing is waiting on it: a `pending` operation is
scheduled and a terminal one is finished, and this is the one state with neither property. It is the
only case in the lifecycle that needs a reaper.

## What the reaper does

The maintenance duty runs on the worker loop **every 15 minutes**. On each pass it takes every
operation still `running` whose `startedAt` is older than the lease, which is **2 minutes**, and
finishes it as a failure whose `error.code` is `lease_expired`.

It is a failure rather than a bare return to the queue, and that is deliberate:

- The ordinary retry rule then applies, so the operation comes back as `pending` with `attempt`
  raised by one and its next run behind the usual backoff.
- The attempt bound therefore applies to a dying worker exactly as it applies to a raising solver.
  An operation no worker survives fails terminally at **3 attempts** instead of looping forever.
- One place increments `attempt`.

So a stuck operation resolves in at most 15 minutes plus the lease, without an operator.

## Surviving capability

- The previous live plan for the week is untouched and still projected. Nothing was lost.
- Every other week is unaffected: each week is planned and solved in its own transaction.
- The operation's `statement` field says this to the user in one sentence, and the Week screen reads
  `solving` until the retry finishes.

## How to force it

There is no route that steps an operation, by design: an operation is created by the mutation whose
work it tracks. So forcing the reaper means running the duty, and there are two ways.

**Restart the worker.** The maintenance runner's first tick after a boot schedules rather than
sweeps, so the first sweep is one interval after the restart. This is the slower option and it needs
no access beyond a deploy.

```
docker compose restart worker
```

**Run the sweep once, against the deployment's own database.** Faster, and it is the same code path
the loop takes.

```
docker compose exec worker python - <<'PY'
import asyncio
from syncr_api.core.clock import utc_now
from syncr_api.solving.maintenance import OperationMaintenance
from syncr_api.worker.main import build_context

async def sweep() -> None:
    context = build_context()
    try:
        async with context.database.sessionmaker() as session, session.begin():
            print(await OperationMaintenance(session, utc_now).sweep())
    finally:
        await context.database.engine.dispose()

asyncio.run(sweep())
PY
```

It prints what it did: how many claims it reaped and how many terminal rows it pruned.

## When the reaper is not the answer

| What you see | What it means |
|---|---|
| The row is `running` and `startedAt` is under 2 minutes old | Inside its lease. A solve is budgeted at under 2 seconds, so a claim this young is either a slow solve or a worker that has just died; wait out the lease |
| The row returns to `pending` and is claimed and reaped again, repeatedly | The work itself kills the worker. Read the worker's logs for the tick that claimed it; the reaper is doing its job and the fault is in the duty |
| `attempt` reached 3 and the row is `failed` with `lease_expired` | The bound did its work. Nothing will retry it, and the week keeps its previous plan. See `solve-failing.md` |
| The row is `running` for a week with no plan at all | The plan horizon maintainer was bringing the week into range. Once the retry succeeds the week gets its plan; until then the Week screen states that the week is not planned |

## Retention

A reaped operation that fails terminally is kept **90 days**, because a failure is diagnostic. One
that succeeded on a later attempt is kept **30 days**. The maintenance duty prunes both, and it
prunes nothing else: the plan's own history is `plan_revisions`, which is never pruned.
