/* What the day will say once a write lands, computed from what it says now.
 *
 * THE OPTIMISM IS ONLY HONEST BECAUSE THE ANSWER IS DERIVABLE. Recording an outcome replaces one row's
 * outcome and nothing else, and confirming a day stamps every row that carries no instant yet: both are
 * rules this module can state completely, which is what "optimistic only where the server response is
 * fully predictable" means. A solve's output is not derivable and is never projected.
 *
 * THE TWO HEADER FIGURES ARE RECOMPUTED RATHER THAN ADJUSTED. `presumedCount` is how many rows nobody has
 * said anything about and `confirmedAt` is the earliest instant, taken only when every row carries one, so
 * both are read back off the projected rows. Adjusting them by a delta would need a second statement of
 * what a presumed row is, and the two would disagree the first time a row already carried an outcome.
 *
 * `unconfirmedDays` is left alone. It counts days BEFORE the day on screen, so no write this screen makes
 * can change it, and a backfill invalidates the key rather than projecting one.
 *
 * Pure: no React, no client, no clock. The instant a write happens at arrives as an argument. */

import type { components } from "../schema";

export type Day = components["schemas"]["DayResponse"];
export type DayRow = components["schemas"]["LedgerRowResponse"];
export type Outcome = components["schemas"]["OutcomeResponse"];
export type OutcomeState = components["schemas"]["OutcomeState"];

/** What a row says happened, which is `presumed` until it says otherwise: the absent row is O1. */
export function stateOf(row: DayRow): OutcomeState {
  return row.outcome?.state ?? "presumed";
}

/** When the day this row belongs to was answered for, or null while nobody has. */
function confirmedAtOf(row: DayRow): string | null {
  return row.outcome?.confirmedAt ?? null;
}

/**
 * When the day was settled, or null when at least one of its rows carries no instant.
 *
 * The earliest, because that is when the user answered for the day: a block added by a later re-solve and
 * confirmed afterwards leaves the day unsettled until it too is confirmed, and does not move the instant.
 * Compared as instants rather than as text, because two stamps may carry two offsets.
 */
function settledAt(rows: readonly DayRow[]): string | null {
  const stamps: string[] = [];
  for (const row of rows) {
    const stamp = confirmedAtOf(row);
    if (stamp === null) return null;
    stamps.push(stamp);
  }
  if (stamps.length === 0) return null;
  return stamps.reduce((earliest, stamp) =>
    Date.parse(stamp) < Date.parse(earliest) ? stamp : earliest,
  );
}

/** The day carrying these rows, with the two figures derived from them recomputed. */
function mapRows(day: Day, change: (row: DayRow) => DayRow): Day {
  const behind = day.behind.map(change);
  const ahead = day.ahead.map(change);
  const rows = [...behind, ...ahead];
  return {
    ...day,
    behind,
    ahead,
    presumedCount: rows.filter((row) => stateOf(row) === "presumed").length,
    confirmedAt: settledAt(rows),
  };
}

/** What one block's outcome carries, as the api answers with it. */
export interface RecordedOutcome {
  readonly state: OutcomeState;
  readonly actualMinutes?: number | null | undefined;
  readonly actualInterval?: { readonly start: string; readonly end: string } | null | undefined;
}

/**
 * The day with one block's outcome replaced.
 *
 * A block the day does not hold changes nothing, which is the honest projection of a 404: the ledger the
 * reader is looking at does not have that row, so there is nothing to show them optimistically.
 *
 * `occurredAt` is the block's own start, and the instant the day was settled at is carried over: recording
 * does not confirm a day and correcting a state does not move the instant the user answered at.
 */
export function withRecordedOutcome(day: Day, blockId: string, recorded: RecordedOutcome): Day {
  return mapRows(day, (row) => {
    if (row.blockId !== blockId) return row;
    const outcome: Outcome = {
      blockId,
      state: recorded.state,
      actualMinutes: recorded.actualMinutes ?? null,
      actualInterval: recorded.actualInterval ?? null,
      occurredAt: row.interval.start,
      confirmedAt: confirmedAtOf(row),
    };
    return { ...row, outcome };
  });
}

/**
 * The day with every row answered for, as confirming it leaves them.
 *
 * A row with no outcome gains a `presumed` one, which is what the presumption being written down looks
 * like, and a row that already carries an instant keeps it: a day confirmed twice stays settled at the
 * instant it was first settled at. A row carrying a recorded exception keeps its state, because confirming
 * says the user has nothing to add rather than that everything happened.
 *
 * A DAY-LEVEL CONFIRMATION COVERS A BLOCK THAT HAS NOT ENDED, so the rows ahead are stamped too. The
 * sections say which rows have been recorded; the confirmation says the user has answered for the day, and
 * a day's last block routinely ends on the next one.
 */
export function withConfirmedDay(day: Day, at: string): Day {
  return mapRows(day, (row) => {
    const outcome: Outcome = row.outcome ?? {
      blockId: row.blockId,
      state: "presumed",
      actualMinutes: null,
      actualInterval: null,
      occurredAt: row.interval.start,
      confirmedAt: null,
    };
    return { ...row, outcome: { ...outcome, confirmedAt: outcome.confirmedAt ?? at } };
  });
}
