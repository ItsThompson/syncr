/* THE BAND'S ZOOM SEGMENT: the reported range as a control, one segment per level.
 *
 * THE SEGMENT IS THE REPORT'S READER, not a range of its own. The grid answers with every level from 6 to 24,
 * marked with whether this display can draw it, and this control renders that answer whole: a display whose cap
 * is 16 still offers 17 through 24, because the count is what tells the reader how deep the range goes and a
 * shortened range reads as a missing feature.
 *
 * AN UNAVAILABLE LEVEL IS OFFERED AS UNAVAILABLE WITH ITS OWN REASON, never hidden and never summarised. Each
 * disabled segment carries the words its report gave it in its accessible name, so the per-level sentence
 * reaches a reader instead of dying in a field nothing renders; striking the figure through keeps the mark on a
 * channel forced-colors mode cannot take away.
 *
 * THE PICKED LEVEL IS THE DRAWN ONE, stated once with `aria-pressed`. The band passes the grid's own answer, so
 * a pressed 16 over a display whose cap is 16 is the truth; passing the level the reader asked for here would be
 * the falsehood the reading this control replaces committed.
 *
 * A PICK UPDATES THE PREFERENCE. Activating an available segment stores those hours immediately, while repeated
 * `z` presses coalesce. An unavailable segment cannot be activated, which is what its reason explains.
 *
 * NOTHING HERE MOVES. The pressed mark is an underline, drawn and not animated, like every state in this kit. */

import type { ZoomLevel } from "../../../ui/domain";

export interface ZoomSegmentProps {
  /** Every level of the range the grid last reported, each marked with whether this display can draw it. */
  readonly levels: readonly ZoomLevel[];
  /** The level the grid is drawing, which is the one segment pressed. */
  readonly pickedHours: number;
  /** Selecting a level, which updates the same preference as `z`. */
  readonly onPick: (hours: number) => void;
}

export function ZoomSegment({ levels, pickedHours, onPick }: ZoomSegmentProps) {
  return (
    <fieldset
      aria-label="Visible hours"
      className="flex flex-wrap items-center gap-0.5 border-0 p-0"
    >
      {levels.map((level) => {
        const isPicked = level.hours === pickedHours;
        return (
          <button
            key={level.hours}
            aria-label={
              level.unavailableReason === null
                ? undefined
                : `${level.hours}h · ${level.unavailableReason}`
            }
            aria-pressed={isPicked}
            className={
              isPicked
                ? "px-1 font-mono text-sm text-ink-deep underline decoration-2 underline-offset-4"
                : level.isAvailable
                  ? "px-1 font-mono text-sm text-ink"
                  : "px-1 font-mono text-sm text-text-muted line-through"
            }
            disabled={!level.isAvailable}
            onClick={() => onPick(level.hours)}
            type="button"
          >
            {level.hours}h
          </button>
        );
      })}
    </fieldset>
  );
}
