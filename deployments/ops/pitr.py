"""The point-in-time rehearsal's ninth claim: WHICH instant the copy came back at.

``python3 -m ops.pitr <asked-for> <dump-instant> <found-at-target> <found-at-dump-instant>``

`just restore-drill` judges eight claims (:mod:`ops.compare`) over the restored copy, and every one
of them would hold just as well for a copy that came back at THE DUMP'S OWN INSTANT: not one of them
can tell the instant a dump was taken from the instant a recovery asked for. That seam is what
``just drill-pitr-local`` exists to bite on, so its verdict adds this claim beside the eight, and it
is stated so it can fail in BOTH directions a fake recovery fails in:

- **The target was ignored.** The row is present at BOTH instants, including the dump's own, where
  by construction it cannot be. That is a replay of everything wearing recovery's clothes: the WAL
  was read and ``recovery_target_time`` decided nothing.
- **Nothing replayed.** The row written after the base backup is missing even at the later instant
  asked for. That is a dump restore wearing recovery's clothes: the bytes came back and no archived
  WAL was read at all.
"""

from __future__ import annotations

import sys

from ops.verdict import Finding

EXIT_OK = 0
EXIT_FAILED = 1

USAGE = (
    "usage: python3 -m ops.pitr <asked-for instant> <dump instant> "
    "<rows found at the target> <rows found at the dump instant>"
)


def main() -> int:
    """Judge the ninth claim from the four figures the recipe read. Returns the exit status."""
    if len(sys.argv) != 5:
        print(USAGE, file=sys.stderr)
        return EXIT_FAILED
    try:
        found_at_target = int(sys.argv[3])
        found_at_dump_instant = int(sys.argv[4])
    except ValueError:
        print(f"{USAGE}, with two counts as numbers", file=sys.stderr)
        return EXIT_FAILED

    finding = claim(
        asked_for=sys.argv[1],
        dump_instant=sys.argv[2],
        found_at_target=found_at_target,
        found_at_dump_instant=found_at_dump_instant,
    )
    print("")
    print("POINT-IN-TIME REHEARSAL")
    print(f"  {finding}")
    print("")
    if finding.held:
        print(
            "The database came back at the instant ASKED FOR, and not at the instant of the dump."
        )
        return EXIT_OK
    print("The claim did not hold.", file=sys.stderr)
    return EXIT_FAILED


def claim(
    *,
    asked_for: str,
    dump_instant: str,
    found_at_target: int,
    found_at_dump_instant: int,
) -> Finding:
    """Judge one rehearsal from two readings of the row that was written after the dump."""
    if found_at_dump_instant > 0:
        return Finding(
            held=False,
            claim=(
                f"the replay ignored the instant asked for ({asked_for}): the row written after "
                f"the dump ({dump_instant}) is present at BOTH instants, including the dump's "
                "own, where by construction it cannot be. This is a replay of everything wearing "
                "recovery's clothes."
            ),
        )
    if found_at_target == 0:
        return Finding(
            held=False,
            claim=(
                f"nothing replayed: the row written after the dump ({dump_instant}) is missing "
                f"even at the later instant asked for ({asked_for}), so the bytes came back and no "
                "archived WAL was read. This is a dump restore wearing recovery's clothes."
            ),
        )
    return Finding(
        held=True,
        claim=(
            f"a recovery asked for {asked_for} came back at THAT instant, and not at the dump's "
            f"({dump_instant}): the row written after the dump is present at the target and absent "
            "at the dump's own instant"
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
