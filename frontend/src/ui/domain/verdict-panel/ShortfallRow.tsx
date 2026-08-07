/* ONE QUANTIFIED GAP: what cannot be satisfied, by how much, by when, and against which of the reader's own rules.
 *
 * THE FIGURE ALONE IS NOT ACTIONABLE, which is why `honoring` is a row rather than being dropped: `1h20m short on
 * Career` says less than the same figure beside `Fitness floor 5h`, because the second names the declaration that
 * produced it. The deadline is a row for the same reason, where one applies.
 *
 * THE ROWS ARE `ReasonRows`, so a gap's labels line up with a reason record's in the detail panel beside it. Two
 * label columns of different widths on one screen is the drift `--clause-label-w` exists to prevent. */

import { ReasonRows, type LabelledRow } from "../reason-rows";
import type { VerdictShortfall } from "./verdict";

export interface ShortfallRowProps {
  readonly shortfall: VerdictShortfall;
}

export function ShortfallRow({ shortfall }: ShortfallRowProps) {
  return (
    <div className="verdict-panel__row">
      <div className="verdict-panel__statement">
        <p>{named(shortfall)}</p>
        <ReasonRows rows={rowsOf(shortfall)} />
      </div>
      <span className="verdict-panel__recovers">{shortfall.shortfall} short</span>
    </div>
  );
}

/** What cannot be satisfied, in the user's own words for it. */
function named(shortfall: VerdictShortfall): string {
  const against = shortfall.against.join(", ");
  return against === "" ? "A commitment cannot be satisfied" : against;
}

function rowsOf(shortfall: VerdictShortfall): LabelledRow[] {
  const rows: LabelledRow[] = [];
  if (shortfall.deadline !== null) rows.push({ label: "due", value: shortfall.deadline });
  if (shortfall.honoring.length > 0) {
    rows.push({ label: "honoring", value: shortfall.honoring.join(", ") });
  }
  return rows;
}
