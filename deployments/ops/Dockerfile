# syntax=docker/dockerfile:1

# =============================================================================
# The syncr ops image: the nightly backup, WAL shipping, and the restore drill.
#
# FROM THE SAME PINNED POSTGRES IMAGE THE DEPLOYMENT RUNS, and that is the whole
# reason this image exists rather than a script on the host. `pg_dump` and
# `pg_restore` here are the 16.10 build, byte for byte the one serving the
# database, so an archive written by one and read by the other cannot be a version
# mismatch discovered during a recovery.
#
# Three tools on top, and nothing else:
#
#   python3     the `ops` package: standard library only, so there is no
#               requirements file, no resolver, and nothing to drift
#   gnupg       hybrid encryption to a public key whose private half is off-host
#   rclone      the off-host bucket, configured entirely from environment
#               variables so no credential is ever written to a file
#
# `ops` is COPIED rather than installed. It is not a workspace member: it must run
# beside `pg_dump` in an image with no application package, and the alerting
# crossing in `test_alert_rules.py` would rightly fail a member whose source names
# `syncr_backup_last_success_timestamp_seconds`, which no process registers.
#
# THE APPLICATION IMAGE IS NOT INVOLVED IN THE DUMP, and this one holds no
# application code. The one reading that needs both worlds is the fingerprint the
# restore is checked against, because the rotation cursor is a domain projection:
# `syncr-plan-fingerprint` runs in the api image and writes into the volume this
# one uploads from.
# =============================================================================

FROM postgres:16.10-bookworm AS runtime

# `--no-install-recommends` keeps this to the three tools and their libraries.
# The apt lists are removed in the same layer, so they are not in the image at all.
#
# `python3`, NOT `python3-minimal`. Debian's minimal package is a REDUCED STANDARD
# LIBRARY: it has no `dataclasses` and no `json`, so `import ops.environment` fails at
# its first import. Measured, in this image, by running the first step of a real backup.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        python3 \
        gnupg \
        rclone \
        gzip \
    && rm -rf /var/lib/apt/lists/*

# `/opt` on the path, so `python3 -m ops.dump` resolves the package under its own
# name: the same name the api suite imports it as, so a test and the deployment run
# the same module.
COPY deployments/ops /opt/ops
ENV PYTHONPATH=/opt

# ROOT, deliberately, and it is the one image here that is. Two of its steps need
# it: draining the WAL staging volume, whose files Postgres wrote as its own user,
# and establishing that volume's ownership so `archive_command` can write there at
# all. Everything it touches is a volume this deployment owns.
USER root

WORKDIR /var/backups/syncr

# No default command: every use is one explicit step, named at the call site by
# `just backup-now` or `just restore-drill`.
ENTRYPOINT []
CMD ["python3", "-c", "import ops; print(ops.__doc__)"]
