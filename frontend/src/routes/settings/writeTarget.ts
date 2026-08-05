/* The one source holding the write-target role, and the reading it carries.
 *
 * ONE PLACE FOR THE NARROWING, because two surfaces ask the same question of the same list: the Settings panel
 * renders the calendar, the horizon and the destructive sentence, and the setup ledger states which calendar the
 * last step named. `writeTarget` is present only on the source holding the role, so finding the source and reading
 * its reading are one act rather than two: a caller that did them separately would have to narrow the field twice
 * and could narrow it against a different row.
 *
 * THE FIELD IS OPTIONAL AND NULLABLE ON THE WIRE, which is two ways of saying absent and neither of which a screen
 * should have to tell apart. What comes back here is a pair or null. */

import type { CalendarSource } from "../../api/hooks/useCalendarSources";

/** What syncr writes to, and what it does to it. */
export type WriteTargetReading = NonNullable<CalendarSource["writeTarget"]>;

/** The source holding the role, paired with its reading. */
export interface WriteTarget {
  readonly source: CalendarSource;
  readonly reading: WriteTargetReading;
}

/** The write target, or null when no calendar holds the role. */
export function writeTargetOf(sources: readonly CalendarSource[]): WriteTarget | null {
  for (const source of sources) {
    const reading = source.writeTarget;
    if (reading !== null && reading !== undefined) return { source, reading };
  }
  return null;
}
