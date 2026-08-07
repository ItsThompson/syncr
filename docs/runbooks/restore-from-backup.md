# Restoring from a backup

## Conventions used below

Two shorthands, and one export the drill needs. Paste this block first; every command in this file
assumes it.

```
cd /opt/syncr
DEPLOY="-f docker-compose.yml -f docker-compose.monitoring.yml -f docker-compose.deploy.yml -f docker-compose.tunnel.yml"
OPS="-f docker-compose.yml -f docker-compose.deploy.yml"
export SYNCR_BACKUP_PRIVATE_KEY=/run/secrets/backup-recipient-private.asc
set -a; . deployments/digests.env; set +a     # the release's pinned images
```

`$DEPLOY` and `$OPS` are the two compose sets this deployment has. **`just` recipes need neither**:
they carry the same sets by default and read `deployments/digests.env` themselves, so prefer the recipe
wherever one exists. The raw commands are here for the steps no recipe covers.

## Trigger

One of three, and the third is the one that runs on a healthy deployment:

- **Data loss or corruption.** Rows are gone, or a migration did something it should not have.
- **The host is gone.** A rebuild starts here, after `deploy-and-rollback.md` brings a stack up.
- **The scheduled drill.** Executed once before the deployment is considered live, and
  **re-executed after any change to the backup path**. `BackupStale` firing is not this runbook: that
  is `backup-stale.md`, which is about the backup not happening.

## What exists to restore from

```
nightly 03:00 host time        pg_dump --format=custom --compress=9, encrypted, off-host
continuous, every minute       WAL segments, compressed, encrypted, off-host

recovery point objective       under 5 minutes
recovery time objective        under 1 hour
retention                      7 daily, 4 weekly, 6 monthly
```

Both are encrypted **to a public key**, and the private half is **not on the host**. That is the whole
point of the arrangement: whoever reaches the VPS reaches the database, and reaching the bucket gains
them nothing. It also means **a restore needs a person with the private key**, which is why the drill
is the only thing that proves the arrangement works.

## The drill: one command, and a person reads the result

```
just restore-drill
```

It needs the private key, which the conventions block above exports, and it composes the release's
pinned digests itself. On a host with no `deployments/digests.env` it stops at compose's own message
naming the missing variable, which is the correct refusal: a drill against a host-built image proves
the backup against something the deployment does not run.

Six steps, none of which touches the live database:

| Step | What it does | What it refuses |
|---|---|---|
| 1 fetch | Downloads the newest dump and its fingerprint, decrypts both, verifies the archive | A bucket with no backup; a truncated or empty archive; a dump of another database |
| 2 scratch | Starts a clean Postgres, in a container with no volume | |
| 3 restore | `pg_restore --exit-on-error` into it | A target that IS the live database; a target that already holds tables |
| 4 migrate | `alembic upgrade head`, the one-shot a deploy runs | |
| 5 boot | The api against the copy, waiting for its own `/readyz` | A copy `/readyz` will not serve |
| 6 compare | The same fingerprint reader, against the manifest | Rows lost; **content that changed with the counts intact**; a cursor that re-derives differently; a drill with nothing to lose |

**Read the seven claims it prints.** The exit status is not the result: `pg_restore` exits 0 having
restored an empty archive, which is why the pass condition is data read back.

```
RESTORE DRILL
  PASS  every one of the 36 tables the dump was taken over is present
  PASS  no table came back short: 11 rows before the dump, 11 after the restore
  PASS  every one of the 5 tables hashes identically, so the rows came back byte for byte
  PASS  the plan history, outcomes, pins, adjustments and edit events all held rows before the dump
  PASS  1 of 1 rotation cursors had advanced before the dump
  PASS  all 1 rotation cursors re-derive to the variant they were on
  PASS  the restored copy is at migration head 0042_pending_weights
  PASS  the restore completed in 17s, inside the 3600s recovery time objective
```

Two of the eight are about the DRILL rather than the backup, and a FAIL on either means the run proved
nothing rather than that the backup is broken:

- *the five evidence tables held rows before the dump*. An empty table restores perfectly. On a
  deployment with no plan history yet, seed it and re-run.
- *a rotation cursor had advanced*. A cursor at index 0 with no confirmations re-derives correctly from
  no data at all. Confirm one rotation habit's occurrence and re-run.

**Record the result.** Date, the eight claims, the elapsed time, and the backup's name. A drill whose
outcome nobody wrote down is a drill that will be argued about.

## A real restore, into the live stack

The drill is a rehearsal of everything below except the last step. **Read the whole section before
starting**, because step 3 is the point of no return.

### 1. Decide what you are recovering to

| Situation | Recover to |
|---|---|
| A bad migration or a bad write, noticed within minutes | The most recent WAL position before it. Point-in-time recovery |
| Corruption of unknown age | The newest nightly dump, then decide whether to replay WAL forward |
| The host is gone | The newest nightly dump plus every WAL segment after it |

### 2. Prove the copy first

```
just restore-drill
```

**Run the drill before the real restore, always.** It takes under a minute, it touches nothing, and it
is the difference between knowing the copy is good and hoping. A drill that fails here means the real
restore would have failed after you had already dropped the live database.

### 3. Stop everything that writes

```
docker compose $DEPLOY down api worker         # the two processes that write
docker compose $DEPLOY stop cloudflared        # and the ingress, so nothing arrives
```

Leave `postgres` running. The learning timer writes too:

```
systemctl stop syncr-learning.timer syncr-backup.timer
```

### 4. Restore

The dump is restored into a **new** database rather than over the live one, so the old data is still
there if the restore turns out to be wrong.

```
# In the ops container, which has pg_restore 16.10 and the decrypted copy from the drill:
docker compose $OPS run --rm ops psql -c 'CREATE DATABASE syncr_restored'
docker compose $OPS run --rm -e PGDATABASE=syncr_restored ops \
  pg_restore --dbname syncr_restored --no-owner --no-privileges --exit-on-error \
  /var/backups/restore/restore.dump
```
For point-in-time recovery, WAL replay needs a `recovery.signal` and a `restore_command` in the
restored data directory rather than a `pg_restore` into a running server. That path is **not verified
on this deployment**: see "Not verified" below.

### 5. Point the stack at it

`DATABASE_URL` is composed in `docker-compose.yml` from `POSTGRES_DB`. Set it in the host secret file
(`.env`) and bring the stack back:

```
POSTGRES_DB=syncr_restored
```

```
docker compose $DEPLOY run --rm --no-deps api alembic upgrade head
docker compose $DEPLOY up -d api worker frontend cloudflared
just await-ready
```

### 6. Verify with data, not with a green container

```
just backup-now                                   # its first step writes a fingerprint of the live database
```

Compare it against the manifest that came with the dump: the same eight claims, by hand. Then look at
the product: the Week screen for a past week, the Today ledger, one Area's budget. **A stack that boots
is not a stack that recovered.**

### 7. Turn the timers back on

```
systemctl start syncr-backup.timer syncr-learning.timer
systemctl start syncr-walship.timer
just backup-now                                   # a fresh copy of what you just recovered to
```

The last line matters: the recovered database has no backup of its own until one runs, and the WAL
lineage changed when the restore did.

## What a FAIL means, claim by claim

| Claim that failed | What it means |
|---|---|
| tables absent after the restore | The archive is incomplete. Try the previous backup; retention keeps 7 daily, 4 weekly, 6 monthly |
| rows came back short | The archive is not what the fingerprint described. Suspect the dump rather than the restore, and check whether the disk was full at 03:00 |
| content differs with the counts intact | The rows are there and their BYTES are not what was dumped. Either the restore altered them, or something wrote between the fingerprint and the dump: if the second, re-run the drill rather than accepting this one. Do not accept a restore that fails this |
| a cursor re-derives differently | Some outcome rows did not arrive. The product would train the wrong muscle group and nothing else would notice. Do not accept this restore |
| not at the shipped migration head | Step 4 did not run, or the chain has more than one head. `just migration-heads` |
| past the recovery time objective | The copy is good and the promise is not. Record the figure; an hour is the number this deployment claims |
| the archive would not decrypt | The private key is not the one the dump was encrypted to. Check `rotate-secrets.md`: rotating the backup key means every earlier copy needs the earlier key |

## Not verified

Stated plainly, because a runbook that reads as tested when it is not is worse than one that says so:

- **Point-in-time recovery has never been executed on this deployment.** WAL archiving runs and the
  segments are in the bucket, and no recovery has replayed them into a restored data directory. The
  five-minute recovery point rests on the archiving working, which is monitored, and on a replay
  procedure that has not been rehearsed.
- **The drill has been executed against a LOCAL bucket, not the deployed one.** `just drill-local`
  exercises every step of the path, including gpg, rclone, retention and the comparison, with the
  bucket as a local rclone remote. The first drill against the real bucket, the real keys and the real
  host is the one this deployment's own criterion names, and it is a human step.
- **Steps 3 through 7 of the real restore have not been run.** They are the drill's steps plus a
  database swap; the swap is the part nobody has done here.
