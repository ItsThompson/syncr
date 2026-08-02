/* The quarter hour, and the two steps a figure moves by.
 *
 * Snap is 15 minutes, and it is MEASURED rather than chosen: in a real reference month every timed block
 * began and ended on a quarter hour, 92% of them on the hour or the half hour, and not one at :05, :10 or
 * :20. `--snap` in `tokens/layout.css` is where that decision lives, and `quarterHour.test.ts` reads the
 * token and requires this constant to equal it. A media query cannot read a custom property and neither
 * can TypeScript, so the duplicate is made incapable of drifting instead of being avoided.
 *
 * A RECORDED ACTUAL IS NOT A PLAN, which is why there is a second step. The Today ledger's partial
 * outcome asks how many minutes something really took, and nothing about a measurement lands on a grid.
 * Five is small enough to be honest and coarse enough that the common correction is two keystrokes. */

/** Minutes between quarter-hour marks. Equal to `--snap`, asserted against the token. */
export const SNAP_MINUTES = 15;

/** Minutes a recorded actual steps by. A measurement, not a placement, so it is not the snap. */
export const RECORDED_STEP_MINUTES = 5;

const MINUTES_IN_DAY = 24 * 60;

/** The nearest multiple of `step`, rounding halves up, never below zero. */
export function snapMinutes(minutes: number, step: number): number {
  if (step <= 0) return Math.max(0, Math.round(minutes));
  return Math.max(0, Math.round(minutes / step) * step);
}

/** Minutes since midnight for a `HH:MM` clock time, or null when the text is not one. */
export function parseClock(text: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text.trim());
  if (match === null) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

/** A `HH:MM` clock time for minutes since midnight, zero-padded so a column of them aligns. */
export function formatClock(minutes: number): string {
  const clamped = Math.max(0, Math.min(MINUTES_IN_DAY - 1, Math.round(minutes)));
  const hours = Math.floor(clamped / 60);
  return `${String(hours).padStart(2, "0")}:${String(clamped % 60).padStart(2, "0")}`;
}

/**
 * A clock time snapped to the nearest quarter hour, or null when the text is not a clock time.
 *
 * 23:53 snaps DOWN to 23:45 rather than up to the next day. A time control's value is a clock time on the
 * day the caller is editing, and rolling it to 00:00 would silently move an interval to the day before,
 * which the caller cannot see in a field showing four characters.
 */
export function snapClock(text: string): string | null {
  const minutes = parseClock(text);
  if (minutes === null) return null;
  const snapped = snapMinutes(minutes, SNAP_MINUTES);
  const lastMarkOfDay = MINUTES_IN_DAY - SNAP_MINUTES;
  return formatClock(Math.min(snapped, lastMarkOfDay));
}
