# Under 20% of the root filesystem is free

## Trigger

`DiskFillingUp` fires. It is a **warning**.

```
absent(node_filesystem_avail_bytes{mountpoint="/"})
or node_filesystem_avail_bytes{mountpoint="/"}
   / node_filesystem_size_bytes{mountpoint="/"} < 0.2
```

It waits **30 minutes**.

This file is `disk-pressure.md`, which is the name section 21 gives the procedure, and it is the one
the alert points at.

## Why this is a warning and why you should still act today

**Everything works until it does not.** Postgres, the api and the worker are all healthy at 19% free
and all three stop at 0%, with no intermediate degradation and no in-product warning. A full disk stops
writes, and Postgres handling a full volume is not a graceful failure. Act while it is a warning.

## Read the `absent()` term first

The absent disjunct covers **the node exporter being down**, which would otherwise look exactly like
plenty of space: a missing series satisfies no threshold, so a threshold-only rule goes quiet at the
moment it loses its ability to see. Check which case you are in before doing anything about disk:

```
up{job="node"}
node_filesystem_avail_bytes{mountpoint="/"}
```

If the second returns nothing, this is an exporter problem and the disk may be fine.

## 20% of what, and why this means something unexpected

The database grows at roughly **16 MB per user-year**. On an 80 GB volume that is generous by orders of
magnitude, so this alert firing is a signal that something is consuming space that is not the product's
data. Growth is not the hypothesis to start from.

## First checks, in the order that usually finds it

```
df -h /
docker system df                      # images, containers, volumes, build cache
du -sh /var/lib/docker/containers/*    # a container log with no rotation
```

| Usual cause | What to do |
|---|---|
| **Container logs with no rotation** | The most common cause by a wide margin. Check `docker inspect` for a log driver with no `max-size`. Truncating a live log file is safe; deleting it while the daemon holds it is not |
| Old images and build cache | `docker image prune`, `docker builder prune`. Safe |
| Dangling volumes from removed stacks | `docker volume ls -f dangling=true`. **Read the list before pruning**: a volume you do not recognise may be a database |
| Postgres WAL not being archived or recycled | Check `pg_wal` size. WAL that cannot be archived accumulates without bound, and this is the one case where the fix is not deleting files. See below |
| The WAL staging volume not being drained | `syncr_wal_archive` holds a segment for at most one shipper interval. A shipper that has stopped leaves them: `systemctl status syncr-walship.timer`, and `BackupStale` fires at fifteen minutes |
| The backup staging volume | `syncr_backup_staging` holds a dump for as long as it takes to encrypt and upload it, and the dump step deletes both copies whatever happens. A file older than one run means a backup was killed mid-flight; it is safe to delete |

## What is safe to prune, and what is not

The short version: **plan data is not prunable, and nothing in this deployment prunes it.**

| Safe | Not safe |
|---|---|
| Docker images, build cache, stopped containers | Anything under a Postgres data directory |
| A stale file in `syncr_backup_staging` | `syncr_wal_archive` segments that have not been shipped. **They are the recovery point** |
| Prometheus data, at the cost of history | `pgdata`, ever |

There is **no pruning policy for plan data in P0** and that is deliberate: the database grows at
roughly 16 MB per user-year, so 80 GB is not a constraint within any planning horizon and the
append-only guarantee stays unqualified. Two things ARE pruned, both telemetry: terminal operations at
30 days (90 for failures) and idempotency keys at 24 hours.

Off-host, retention keeps **7 daily, 4 weekly and 6 monthly** copies, and it refuses to delete anything
when the listing does not hold the backup the run just uploaded, or when a plan would delete the newest
copy. So the bucket is bounded and the local disk holds no copies at all.

## What not to do

- **Do not delete anything under a Postgres data directory.** Not WAL segments, not anything.
- **Do not `docker system prune -a --volumes`** on a hunch. It removes named volumes, and this
  deployment's database is one.
- Do not stop Postgres to free space. A clean shutdown needs to write.

## Recovery

Once space is recovered, confirm the ratio rather than assuming:

```
node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}
```

The alert clears within one scrape interval plus the 30-minute `for` window.

## Still to be written

- **Log rotation as a deployment default.** This deployment does not set `max-size` on any container's
  log driver, and unbounded container logs are the most likely cause of this alert. That is a
  Compose-level fix rather than a runbook step, and it is ticket **1580**.
- Recovery from a volume that is already at 0%, where Postgres will not start. The steps differ from
  the ones above and none of them is verified here.
- Whether `mountpoint="/"` is the right filesystem on the Linux host. It is what the deployment watches,
  and it has not been confirmed against the host's actual layout: Docker Desktop does not expose the
  same mountpoints, so this term is unverified on this machine.
