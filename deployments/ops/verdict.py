"""The restore drill's verdict: data read back, and never an exit status.

Every check here exists because of a way a drill can pass while the backup path is broken.

- **Every table the manifest names is present after the restore.** A restore that dropped a table
  entirely would not be reported by a row count, because the count itself goes missing with it.
- **No table's count went down.** That is the whole reconciliation, stated as a floor because the
  manifest is read before the dump's snapshot.
- **Every table's contents hash identically.** Counts and cursors cannot see a row's bytes:
  measured, a reviewer replaced every plan document and moved every pin four hundred days, left the
  counts identical, and this verdict reported "the data came back". The ticket's criterion says
  INTACT, which is stronger than "present in the same number".
- **The five evidence tables held rows BEFORE the dump.** Otherwise this is a drill that passed
  because there was nothing to lose: an empty database restores perfectly.
- **At least one rotation cursor had advanced.** The cursor is derived from the outcome log, and one
  sitting at index 0 with no confirmations re-derives correctly from no data at all.
- **Every cursor re-derives to the same variant.** A restore that lost one confirmation gives a
  plausible database whose next session trains the wrong muscle group.
- **The restored copy is at the migration head the code ships.** A restore onto a schema at another
  head is one ``/readyz`` would refuse, and a drill without this check would not mention it.
- **The whole thing fitted inside the recovery time objective.** An hour is the promise; a drill
  that took three disproved it.

The verdict is a list of findings rather than a boolean, because a human confirms the outcome and
what they need is which claim failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ops.config import EVIDENCE_TABLES, RECOVERY_TIME_OBJECTIVE_SECONDS

if TYPE_CHECKING:
    from ops.fingerprint import Fingerprint


@dataclass(frozen=True, slots=True)
class Finding:
    """One claim the drill makes, and whether the two readings bear it out."""

    held: bool
    claim: str

    def __str__(self) -> str:
        return f"{'PASS' if self.held else 'FAIL'}  {self.claim}"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Every finding, in the order a person should read them."""

    findings: tuple[Finding, ...]

    @property
    def held(self) -> bool:
        return all(finding.held for finding in self.findings)

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if not finding.held)


def compare(before: Fingerprint, after: Fingerprint, *, elapsed_seconds: float) -> Verdict:
    """Judge one restore, against the reading taken before the dump it came from."""
    return Verdict(
        findings=(
            _tables_present(before, after),
            _no_count_regressed(before, after),
            _contents_hash_identically(before, after),
            _there_was_data_to_lose(before),
            _a_cursor_had_advanced(before),
            _cursors_rederive(before, after),
            _at_the_shipped_head(after),
            _inside_the_objective(elapsed_seconds),
        )
    )


def _tables_present(before: Fingerprint, after: Fingerprint) -> Finding:
    missing = sorted(before.tables - after.tables)
    return Finding(
        held=not missing,
        claim=(
            f"every one of the {len(before.tables)} tables the dump was taken over is present"
            if not missing
            else f"{len(missing)} tables are absent after the restore: {missing}"
        ),
    )


def _no_count_regressed(before: Fingerprint, after: Fingerprint) -> Finding:
    lost = {
        table: (count, after.row_counts[table])
        for table, count in before.row_counts.items()
        if table in after.row_counts and after.row_counts[table] < count
    }
    return Finding(
        held=not lost,
        claim=(
            f"no table came back short: {before.rows} rows before the dump, {after.rows} after the "
            "restore"
            if not lost
            else f"rows were lost, as (before, after): {dict(sorted(lost.items()))}"
        ),
    )


def _contents_hash_identically(before: Fingerprint, after: Fingerprint) -> Finding:
    """The only claim in this verdict that reads a row's bytes.

    An EQUALITY rather than the floor the counts use, and the asymmetry is deliberate. The digest is
    over the set of rows, so a row appended between the reading and the dump changes it, exactly as
    a lost or altered row does. That case is reported as a failure rather than tolerated, for the
    reason the cursor comparison is: a comparison that cannot distinguish a write from a loss is not
    a comparison. At 03:00 on a deployment with one user the window is seconds, and the remedy is to
    re-run the drill; taking both readings inside one `pg_export_snapshot()` would remove the window
    entirely and is recorded as not taken.

    A reading over ZERO tables REFUSES rather than passing. `ops.fingerprint` already declines to
    parse a document with no digests, but the two guards were sequential rather than independent:
    with the parser's refusal deleted, this claim read "every one of the 0 tables hashes
    identically, so the rows came back byte for byte" and held. A claim that cannot fail is not a
    claim.
    """
    if not before.content_digests:
        return Finding(
            held=False,
            claim=(
                "no table was hashed before the dump, so nothing about the rows themselves is "
                "comparable and this drill says nothing about content. The fingerprint the "
                "manifest was written from is the thing to look at."
            ),
        )
    differing = {
        table: (digest[:12], after.content_digests[table][:12])
        for table, digest in before.content_digests.items()
        if table in after.content_digests and after.content_digests[table] != digest
    }
    unhashed = sorted(set(before.content_digests) - set(after.content_digests))
    return Finding(
        held=not differing and not unhashed,
        claim=(
            f"every one of the {len(before.content_digests)} tables hashes identically, so the "
            "rows came back byte for byte"
            if not differing and not unhashed
            else f"content differs, as (before, after) digests: {dict(sorted(differing.items()))}"
            + (f"; and {unhashed} were not hashed after the restore" if unhashed else "")
            + ". Either the restore altered or lost rows, or something wrote between the reading "
            "and the dump: in the second case re-run the drill rather than accepting this one."
        ),
    )


def _there_was_data_to_lose(before: Fingerprint) -> Finding:
    """The drill is inconclusive over a table that was empty when the dump was taken."""
    empty = sorted(
        table
        for table in EVIDENCE_TABLES
        if table not in before.row_counts or before.row_counts[table] == 0
    )
    return Finding(
        held=not empty,
        claim=(
            "the plan history, outcomes, pins, adjustments and edit events all held rows before "
            "the dump, so the comparison is over data that could have been lost"
            if not empty
            else f"{empty} held no rows before the dump, so this drill proves nothing about them. "
            "Seed the deployment and re-run: a restore of an empty table always succeeds."
        ),
    )


def _a_cursor_had_advanced(before: Fingerprint) -> Finding:
    advanced = [cursor for cursor in before.cursors if cursor.confirmed_completions > 0]
    return Finding(
        held=bool(advanced),
        claim=(
            f"{len(advanced)} of {len(before.cursors)} rotation cursors had advanced before the "
            "dump, so re-deriving one is a real comparison"
            if advanced
            else "no rotation cursor had advanced before the dump, so a cursor that re-derives to "
            "index 0 says nothing. Confirm a rotation habit's occurrence and re-run."
        ),
    )


def _cursors_rederive(before: Fingerprint, after: Fingerprint) -> Finding:
    """Every field of every cursor, including the VARIANT the claim is stated in terms of.

    The first version compared the key, the index and the completion count and not the variant, so
    a restore that produced the same index against a different variant list would have reported "all
    cursors re-derive to the variant they were on". Today the variant is a function of the index
    over one habit's list, so the two cannot diverge for one configuration; the drill compares
    ACROSS a restore, and the point of a fingerprint is not to assume the two sides agree.
    """
    found = after.cursor_by_key()
    wrong = {
        cursor.key: (cursor.variant, found[cursor.key].variant if cursor.key in found else "absent")
        for cursor in before.cursors
        if cursor.key not in found
        or found[cursor.key].index != cursor.index
        or found[cursor.key].variant != cursor.variant
        or found[cursor.key].confirmed_completions != cursor.confirmed_completions
    }
    return Finding(
        held=not wrong,
        claim=(
            f"all {len(before.cursors)} rotation cursors re-derive to the variant they were on"
            if not wrong
            else f"cursors re-derive differently, as (before, after): {dict(sorted(wrong.items()))}"
        ),
    )


def _at_the_shipped_head(after: Fingerprint) -> Finding:
    at_head = after.applied_revision == after.expected_head
    return Finding(
        held=at_head,
        claim=(
            f"the restored copy is at migration head {after.expected_head}, which is the head this "
            "checkout ships, so `/readyz` can pass against it"
            if at_head
            else f"the restored copy is at {after.applied_revision or 'no revision'} and this "
            f"checkout ships {after.expected_head}: a deploy against it would refuse traffic"
        ),
    )


def _inside_the_objective(elapsed_seconds: float) -> Finding:
    inside = elapsed_seconds <= RECOVERY_TIME_OBJECTIVE_SECONDS
    return Finding(
        held=inside,
        claim=(
            f"the restore completed in {elapsed_seconds:.0f}s, inside the "
            f"{RECOVERY_TIME_OBJECTIVE_SECONDS}s recovery time objective"
            if inside
            else f"the restore took {elapsed_seconds:.0f}s, past the "
            f"{RECOVERY_TIME_OBJECTIVE_SECONDS}s recovery time objective this deployment promises"
        ),
    )
