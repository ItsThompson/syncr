/* THE SUMMARY STRIP. Three readings plus the verdict, at a FIXED height.
 *
 * THE HEIGHT IS A CORRECTNESS RULE, not a preference. The strip sits directly above the grid, and a strip that
 * grew by a line when a verdict arrived would shift the grid under the cursor mid-drag. `Strip` reserves --strip-h
 * whether or not there is anything to say, which is why the verdict cell renders quietly rather than not at all.
 *
 * THREE READINGS, NOT TWO PLUS PER-AREA BARS. The alternative answers "which Area is starving" at a glance and
 * drops the discretionary denominator that makes every percentage mean anything. UNALLOCATED is one of the three
 * because it is the figure nobody has ever looked at, and it is the gap the product exists to close.
 *
 * PLAN CURRENCY IS NOT A FOURTH READING. It rides in the SCHEDULED cell's sub-line, qualifying the count it sits
 * under. */

import { Strip, StatCell } from "../../layout";
import { formatCurrency, formatHours, formatShare, type StripReadings } from "./readings";
import "./strip.css";

/** The verdict the strip states in words, or null while nothing has computed one. */
export interface VerdictReading {
  /** One sentence: what this week can or cannot hold. */
  readonly headline: string;
  /** The shortfall behind it, in the verdict's own words. */
  readonly detail: string;
}

export interface SummaryStripProps {
  readonly readings: StripReadings;
  readonly verdict: VerdictReading | null;
}

export function SummaryStrip({ readings, verdict }: SummaryStripProps) {
  return (
    <Strip height="fixed">
      <div className="week-strip">
        <div className="week-strip__cell">
          <StatCell
            figure={formatHours(readings.scheduledMinutes)}
            label="Scheduled"
            sub={formatCurrency(readings.blockCount, readings.planCurrency)}
          />
        </div>
        <div className="week-strip__cell">
          <StatCell
            figure={formatHours(readings.discretionaryMinutes)}
            label="Discretionary"
            sub="after frame and anchors"
          />
        </div>
        <div className="week-strip__cell">
          <StatCell
            figure={formatHours(readings.unallocatedMinutes)}
            label="Unallocated"
            sub={formatShare(readings.unallocatedMinutes, readings.discretionaryMinutes)}
          />
        </div>
        {verdict === null ? (
          <p className="week-strip__verdict week-strip__verdict--quiet">
            No verdict has been computed for this week yet.
          </p>
        ) : (
          <div className="week-strip__verdict">
            <p>{verdict.headline}</p>
            <p>{verdict.detail}</p>
          </div>
        )}
      </div>
    </Strip>
  );
}
