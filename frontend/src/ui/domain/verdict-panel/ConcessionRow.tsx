/* ONE APPROVED CONCESSION: what this week has already given up, and when the reader agreed to it.
 *
 * A FACT RATHER THAN AN OFFER, so it carries no control. It reads quieter than a gap for the same reason, and it
 * sits above the gaps: a week that has absorbed a concession must not read as simply feasible, or the product
 * reports a healthy week for a reason the reader cannot see. */

import type { VerdictConcession } from "./verdict";

export interface ConcessionRowProps {
  readonly concession: VerdictConcession;
}

export function ConcessionRow({ concession }: ConcessionRowProps) {
  return (
    <div className="verdict-panel__row">
      <p className="verdict-panel__statement verdict-panel__concession">
        {concession.label}
        {concession.approvedOn === null ? null : (
          <span className="verdict-panel__gap">approved {concession.approvedOn}</span>
        )}
      </p>
    </div>
  );
}
