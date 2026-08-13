/* THE WINDOW A CALLER ALREADY KNOWS THE WORK BELONGS IN, and how the form states it.
 *
 * TWO INSTANTS RATHER THAN A WALL TIME, because that is what the week screen holds: an empty slot's interval is
 * two instants on the wire, and turning one into a clock time needs a zone the slot does not carry.
 *
 * THE READING IS WHOLE AT BOTH ENDS. A window inside one local day would read more cheaply as one date and two
 * times, and a window that crosses midnight would then be a sentence naming a day it half belongs to. One rule
 * that cannot mislead is worth more here than the shorter line, because the whole point of stating it is that the
 * reader recognises the slot they came from. */

import { wallOf } from "../../lib/zonedInstant";

/** A stretch of time, as the two instants bounding it. */
export interface CaptureWindow {
  readonly from: string;
  readonly to: string;
}

/**
 * `2026-02-11 14:00 to 2026-02-11 15:00`, both ends on the reader's own wall clock.
 *
 * Null when either instant or the zone cannot be read, which is a window with nothing to say rather than one
 * rendered as a pair of failures.
 */
export function preferredWindowReading(window: CaptureWindow, zone: string): string | null {
  const from = wallOf(window.from, zone);
  const to = wallOf(window.to, zone);
  if (from === null || to === null) return null;
  return `${from.date} ${from.time} to ${to.date} ${to.time}`;
}
