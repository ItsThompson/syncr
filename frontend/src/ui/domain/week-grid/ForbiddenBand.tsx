/* THE BAND THAT EXPLAINS A GAP. One component for all three kinds, because they draw identically.
 *
 * It takes no kind and no reason, and that is the strongest way to state the rule: a forbidden window, an
 * off-plan span and an unfilled template slot differ in what they do to the discretionary denominator and in
 * nothing a reader sees, so there is nothing here for a drawing rule to diverge on.
 *
 * IT IS NOT A BLOCK. No fill, no Area rule, no block state, and it sits under every block in z-order, so a
 * pinned block inside a recovery window still reads as a block.
 *
 * THE LABEL IS THE PAYLOAD'S, NEVER COMPOSED HERE. A window stores its own, so an anchor retitled in March
 * cannot change what a week approved in February says; an off-plan span carries the user's word for it; an empty
 * slot's is rendered by the server from the one wording its reason has. Where there is none the gutter is empty and
 * the band still draws, because it is the absence of a block that the band exists to explain and an unlabelled band
 * explains more than nothing does.
 *
 * THE LABEL IS REAL TEXT, not an adornment in the layout layer's 20px `Gutter`: the measured labels run to about
 * thirty characters, `recovery · Kontron Interview` being one of them, and that column holds a 10px chip. It is
 * knocked out over its own background for the reason the hour label is, that uppercase micro-type over a hatch
 * reads as a smudge rather than as a word. */

import { BandLabel } from "./BandLabel";
import type { Box } from "./geometry";
import "./band.css";

export interface ForbiddenBandProps extends Box {
  /** What the gutter says. Null for a declared off-plan span the user gave no word for. */
  readonly label: string | null;
  /**
   * Activating the gutter label, where the caller has something for it to do.
   *
   * An empty slot's label opens capture prefilled with the slot's Area and duration, which is what turns the slot
   * from a dead end into an invitation. A band with nothing behind it renders its label as text: a control that did
   * nothing would be worse than a reading.
   */
  readonly onActivate?: (() => void) | undefined;
}

const PLACES = 3;

export function ForbiddenBand({ topPx, heightPx, label, onActivate }: ForbiddenBandProps) {
  return (
    <>
      <div
        className="week-band"
        style={{ top: `${topPx.toFixed(PLACES)}px`, height: `${heightPx.toFixed(PLACES)}px` }}
      />
      {label === null ? null : (
        <div className="week-band__label-anchor" style={{ top: `${topPx.toFixed(PLACES)}px` }}>
          <BandLabel label={label} onActivate={onActivate} />
        </div>
      )}
    </>
  );
}
