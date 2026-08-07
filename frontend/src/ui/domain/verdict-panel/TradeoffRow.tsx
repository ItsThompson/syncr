/* ONE TRADEOFF: A STATEMENT PLUS A `Propose` BUTTON. Nothing else, and nothing chosen.
 *
 * syncr NEVER SELECTS A TRADEOFF. The row offers and stops: there is no recommended one, no default, no ordering by
 * preference and no pre-selection. The decision stays the reader's, which is the whole of `US-FEAS-04`, and the
 * panel's test asserts that no row is ever selected.
 *
 * REQUESTING ONE MUTATES NOTHING. The button dispatches a solve against modified inputs and the result lands in the
 * pending slot as a proposal; the plan of record is untouched until the reader approves it. That is why the control
 * says `Propose` rather than `Apply`.
 *
 * THE WORDING IS THE API'S. It is per kind and per target and it names the nights a reduction would touch, so a
 * second wording composed here would be a second statement of one thing. */

import { Button } from "../../primitives";
import type { VerdictTradeoff } from "./verdict";

export interface TradeoffRowProps {
  readonly tradeoff: VerdictTradeoff;
  /** Dispatches the solve. Absent leaves the statement readable with no control, which a read-only view wants. */
  readonly onPropose?: ((tradeoff: VerdictTradeoff) => void) | undefined;
}

export function TradeoffRow({ tradeoff, onPropose }: TradeoffRowProps) {
  return (
    <div className="verdict-panel__row">
      <p className="verdict-panel__statement">
        {tradeoff.label}
        {tradeoff.recovers === null ? null : (
          <span className="verdict-panel__gap">recovers up to {tradeoff.recovers}</span>
        )}
      </p>
      {onPropose === undefined ? null : (
        <Button
          rank="secondary"
          size="sm"
          onClick={() => {
            onPropose(tradeoff);
          }}
        >
          Propose
        </Button>
      )}
    </div>
  );
}
