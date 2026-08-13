/* THE WINDOW A CALLER ALREADY KNOWS THE WORK BELONGS IN: how the form states it, and what the write sends.
 *
 * TWO INSTANTS RATHER THAN A WALL TIME, because that is what the week screen holds: an empty slot's interval is
 * two instants on the wire, and turning one into a clock time needs a zone the slot does not carry.
 *
 * THE READING IS WHOLE AT BOTH ENDS. A window inside one local day would read more cheaply as one date and two
 * times, and a window that crosses midnight would then be a sentence naming a day it half belongs to. One rule
 * that cannot mislead is worth more here than the shorter line, because the whole point of stating it is that the
 * reader recognises the slot they came from.
 *
 * THE DECLARATION DROPS THE DATES, because a preference is a time of day: the api resolves the clock times
 * against whatever zone is in force on each date it reads the window for. An end at midnight is spelled `00:00`
 * and the api reads that as the end of the day, which is the one bound it lets read earlier than its start.
 *
 * BOTH ENDS COME OFF ONE READING, so a window the form could not state is a window the write does not send
 * either. Either half answering null would otherwise leave a sentence and a request disagreeing about the same
 * two instants. */

import { wallOf } from "../../lib/zonedInstant";
import type { PreferredWindow } from "../../api/hooks/useTaskCapture";

/** A stretch of time, as the two instants bounding it. */
export interface CaptureWindow {
  readonly from: string;
  readonly to: string;
}

/** Both ends on the reader's own wall clock, or null when either instant or the zone cannot be read. */
function endsOf(
  window: CaptureWindow,
  zone: string,
): { from: { date: string; time: string }; to: { date: string; time: string } } | null {
  const from = wallOf(window.from, zone);
  const to = wallOf(window.to, zone);
  return from === null || to === null ? null : { from, to };
}

/**
 * `2026-02-11 14:00 to 2026-02-11 15:00`, both ends on the reader's own wall clock.
 *
 * Null when either instant or the zone cannot be read, which is a window with nothing to say rather than one
 * rendered as a pair of failures.
 */
export function preferredWindowReading(window: CaptureWindow, zone: string): string | null {
  const ends = endsOf(window, zone);
  if (ends === null) return null;
  return `${ends.from.date} ${ends.from.time} to ${ends.to.date} ${ends.to.time}`;
}

/** The two clock times a preference declares this window as, or null when it cannot be read in the zone. */
export function preferredWindowDeclaration(
  window: CaptureWindow,
  zone: string,
): PreferredWindow | null {
  const ends = endsOf(window, zone);
  if (ends === null) return null;
  return { start: ends.from.time, end: ends.to.time };
}
