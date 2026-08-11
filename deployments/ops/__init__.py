"""The deployment's own tooling: the nightly backup, WAL shipping, and the restore drill.

Not a workspace member, and deliberately not. Two properties decide that:

- **It must run where `pg_dump` is.** The dump is taken by the `postgres:16.10-bookworm` binaries
  rather than by whatever the host happens to carry, because a dump written by a different major
  version is a dump the deployed server may refuse to restore. So these modules run inside an image
  built FROM the same pinned Postgres image, which has no application package in it at all.
- **It names a metric family no process registers.** ``syncr_backup_last_success_timestamp_seconds``
  is written to a file the node exporter serves, because a script that has exited cannot be scraped.
  The alerting crossing in ``packages/syncr-api/tests/test_alert_rules.py`` reads every
  family-shaped literal in every member's source and requires it to be in the Prometheus registry,
  so a member
  holding that literal would fail a gate that is right to fail.

Every module is standard library only, on Python 3.11, which is what Debian bookworm carries. The
api suite type-checks, lints, and tests this package: see ``packages/syncr-api/pyproject.toml``.

Which side each module runs on:

| Module | Runs |
|---|---|
| ``config`` | both. Every figure the backup path and its runbooks quote |
| ``naming`` | both. Object names, and the timestamp read back out of one |
| ``retention`` | in the ops image. Which objects a listing keeps and which it deletes |
| ``verify`` | in the ops image. Whether a file is a restorable custom-format dump |
| ``exposition`` | in the ops image. The textfile the node exporter serves |
| ``remote`` | in the ops image. rclone, and the refusal to call a local disk off-host |
| ``dump`` | in the ops image. The nightly backup, end to end |
| ``ship`` | in the ops image. WAL segments to the same bucket |
| ``fetch`` | in the ops image. The newest dump back out of the bucket, decrypted |
| ``fetch_segment`` | in the ops image. One WAL segment out of the bucket, for a recovery to copy |
| ``restore`` | in the ops image. Into a scratch database that is not the live one |
| ``compare`` | in the ops image. The drill's verdict, over two fingerprints |
"""
