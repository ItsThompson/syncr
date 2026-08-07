# The database, the api or the worker is unreachable

## Trigger

`DatabaseUnreachable` fires. It is **critical**, and it watches three things rather than one:

```
pg_up == 0 or absent(pg_up)
or up{job="syncr-api"}    == 0 or absent(up{job="syncr-api"})
or up{job="syncr-worker"} == 0 or absent(up{job="syncr-worker"})
```

It waits **2 minutes**, so a restart does not page.

## Read the name before you read the summary

**The alert's name is narrower than what it watches, and that is deliberate: one page for "a process
this deployment depends on is gone".** Before assuming Postgres, find out which target Prometheus
lost. The three cases have nothing in common but the page.

| Target down | What has actually stopped |
|---|---|
| `pg_up` | Everything. Nothing reads and nothing writes |
| `syncr-api` | Every screen and every API call. The worker keeps solving, projecting and polling |
| `syncr-worker` | Solving, projecting, calendar polling and the horizon. **Every screen still works** |

Ask Prometheus directly:

```
up{job=~"syncr-.*"}      # which of our two processes it can reach
pg_up                    # the postgres exporter's own reading
```

If `up` is 1 for both and `pg_up` is 0, the api and worker are alive and the **exporter** may be what
is broken rather than the database: check whether the api still answers `/health`. An exporter that
cannot log in reports `pg_up 0` from a perfectly healthy database.

## Why the worker is in this rule at all

**Every family in the plan pipeline, the calendar and the token age is recorded in the worker
process.** A dead worker takes `WriteTargetTokenExpiring`, `ProjectionFailing`, `SolveFailing`,
`SourceStale`, `HorizonNotMaintained` and `SupersededRatioHigh` silent at the same moment, because a
frozen gauge reads healthy and an absent counter has no increase. So the worker's liveness is not a
convenience: without it, one dead process makes six alerts unable to fire.

Readiness is not something a stopped process can publish, which is why the condition is read from
signals that outlive it: the exporter's `pg_up`, and whether Prometheus can scrape each process at
all.

## Surviving capability

- The calendar on the phone still holds the last projected plan, so today and tomorrow are still
  visible to the user.
- **Nothing is lost.** Every write is either in Postgres or was refused.
- If only the **worker** is gone, every screen still reads and every verdict still computes.

## First checks

```
docker compose ps                       # which container is not running
docker compose logs --tail=200 worker   # or api
docker compose logs --tail=100 postgres
```

An out-of-memory kill is the common cause and it is silent in the application's own logs: check
`docker inspect --format '{{.State.OOMKilled}}' <container>`.

## Recovery

Restarting is safe for all three. There is no cleanup step and no partial state to repair:

- A solve interrupted mid-flight leaves its operation `running`, and the reaper returns it to the
  queue within 15 minutes. See `stuck-operation.md`.
- A projection interrupted mid-flight is recorded as `failed` and retried.
- No migration runs on a plain restart.

```
docker compose up -d postgres
docker compose up -d api worker
```

Then confirm the alert clears rather than assuming it: `up{job=~"syncr-.*"}` and `pg_up` should all
read 1 within one scrape interval.

## Still to be written

- What to do when Postgres will not start because its volume is full. That is `disk-filling-up.md`'s
  subject up to the point the database refuses writes, and the recovery from there is unwritten.
- Restoring from a backup, which needs the backup to exist: ticket 58.
