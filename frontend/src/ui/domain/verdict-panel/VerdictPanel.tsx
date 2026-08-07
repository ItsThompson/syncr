/* THE VERDICT PANEL: what this week can and cannot hold, what it has already conceded, and what could be conceded.
 *
 * PANEL VOLUME, IN AMBER, AS A NOTICE RATHER THAN A FAILURE. A week that cannot hold its commitments is impossible,
 * not broken, and it is the most valuable thing this product computes. Nothing here blocks anything: level 4 of the
 * severity ladder does not exist, and approval stays reachable while this panel says the week is infeasible --
 * including when the reader's own pins caused it.
 *
 * FIXED HEIGHT, ROWS SCROLLING INSIDE. `verdict.css` carries the reasoning: the grid must not shift under the cursor
 * mid-drag, and the fourth row's clipped edge is the scroll affordance.
 *
 * CONCESSIONS ABOVE SHORTFALLS. What has already been given up is stated before what is still missing.
 *
 * A GAP WITH NO REMEDY IS SAID IN WORDS. A served solver verdict carries no tradeoffs today, so a packing failure
 * can arrive with nothing to offer against it. The honest rendering is a row saying the reading enumerated none,
 * rather than a silence a reader would read as "there is nothing to be done". */

import { ConcessionRow } from "./ConcessionRow";
import { ShortfallRow } from "./ShortfallRow";
import { TradeoffRow } from "./TradeoffRow";
import {
  provenanceReading,
  verdictHeadline,
  type PanelVerdict,
  type VerdictConcession,
  type VerdictTradeoff,
} from "./verdict";
import "./verdict.css";

/* A stable empty list, so a panel with nothing conceded does not take a fresh array on every render. */
const NONE: readonly VerdictConcession[] = [];

export interface VerdictPanelProps {
  readonly verdict: PanelVerdict;
  /** What this week has already given up, listed above the gaps. */
  readonly concessions?: readonly VerdictConcession[] | undefined;
  /** Dispatches a solve against modified inputs. Absent renders the offers without controls. */
  readonly onPropose?: ((tradeoff: VerdictTradeoff) => void) | undefined;
}

export function VerdictPanel({ verdict, concessions = NONE, onPropose }: VerdictPanelProps) {
  const hasGapWithNoRemedy = verdict.shortfalls.length > 0 && verdict.tradeoffs.length === 0;

  return (
    <section className="verdict-panel" aria-label="Verdict">
      <div className="verdict-panel__head">
        <p className="verdict-panel__headline">{verdictHeadline(verdict, concessions.length)}</p>
        <p className="verdict-panel__provenance">{provenanceReading(verdict.provenance)}</p>
      </div>
      <div className="verdict-panel__rows">
        {concessions.map((concession) => (
          <ConcessionRow concession={concession} key={concession.id} />
        ))}
        {verdict.shortfalls.map((shortfall) => (
          <ShortfallRow key={shortfall.id} shortfall={shortfall} />
        ))}
        {verdict.tradeoffs.map((tradeoff) => (
          <TradeoffRow
            key={`${tradeoff.kind}:${tradeoff.targetId}`}
            onPropose={onPropose}
            tradeoff={tradeoff}
          />
        ))}
        {hasGapWithNoRemedy ? (
          <div className="verdict-panel__row">
            <p className="verdict-panel__statement verdict-panel__concession">
              This reading names no concession that would recover the gap above. A re-solve
              enumerates them.
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
