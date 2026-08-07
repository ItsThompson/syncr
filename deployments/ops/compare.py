"""The drill's verdict, printed for a person. ``python3 -m ops.compare``.

The last step, and the only one whose output matters to anyone: ``just restore-drill`` automates the
mechanics and a human confirms the outcome, so what this prints is what they read. Every claim is
stated in full whether it held or not, because a drill that printed only failures would leave the
reader unable to tell a pass from a run that checked nothing.

The two readings come from the same reader in the same image, one taken against the live database
before the dump and one against the restored copy after migrations were applied to it. The
comparison is in :mod:`ops.verdict`.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

from ops import environment
from ops.fetch import FETCHED_MANIFEST
from ops.fingerprint import read as read_fingerprint
from ops.verdict import compare

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ops.verdict import Verdict

# What the api one-shot writes against the restored copy, in the scratch volume.
RESTORED_FINGERPRINT = "restored.fingerprint.json"

EXIT_OK = 0
EXIT_FAILED = 1


def main() -> int:
    """Print the verdict. Returns 0 only when every claim held."""
    try:
        verdict = judge(environ=os.environ)
    except Exception as unreadable:  # noqa: BLE001 - one message and a non-zero exit
        print(f"the drill cannot be judged: {unreadable}", file=sys.stderr)
        return EXIT_FAILED

    print("")
    print("RESTORE DRILL")
    for finding in verdict.findings:
        print(f"  {finding}")
    print("")
    if verdict.held:
        print("Every claim held. This backup restores, and the data came back.")
        return EXIT_OK
    print(
        f"{len(verdict.failures)} of {len(verdict.findings)} claims did not hold.",
        file=sys.stderr,
    )
    print("docs/runbooks/restore-from-backup.md names what each one means.", file=sys.stderr)
    return EXIT_FAILED


def judge(*, environ: Mapping[str, str]) -> Verdict:
    """Read both fingerprints and compare them, with the elapsed time the recipe measured."""
    paths = environment.paths(environ)
    before = read_fingerprint(paths.scratch / FETCHED_MANIFEST)
    after = read_fingerprint(paths.scratch / RESTORED_FINGERPRINT)
    return compare(before, after, elapsed_seconds=elapsed(environ))


def elapsed(environ: Mapping[str, str]) -> float:
    """How long the drill took, from the epoch stamp the recipe took before its first step.

    Measured by the caller because the recovery time objective is stated over the WHOLE recovery:
    the fetch, the restore, the migration one-shot and the boot. A figure this process measured
    would only
    ever cover the comparison.
    """
    stated = environment.required(environment.STARTED_AT_VAR, environ)
    return max(0.0, time.time() - float(stated))


if __name__ == "__main__":
    sys.exit(main())
