/* THE REASON RECORD, AND THE DEFINITION ROWS BESIDE IT. One rendering, because they are one form.
 *
 * A COMPONENT THAT TAKES ROWS RATHER THAN A RECORD. Turning six clause kinds into words is the route's business:
 * the kit does not know what a `ClauseResponse` is, and the wording of a clause is bound up with the Area names and
 * the zone a screen resolves. What is shared, and what would otherwise drift between the two surfaces that draw it,
 * is the geometry of the row and the width of its label column.
 *
 * NOTHING IS RENDERED FOR AN EMPTY SET, and that is deliberate rather than an omission: an empty definition list is
 * a labelled region with nothing in it, and a block whose record carries no clause has nothing to explain. The
 * caller says what an absence means, because only the caller knows whether it is "not solved yet" or "no reason
 * recorded". */

import type { LabelledRow } from "./row";
import "./rows.css";

export interface ReasonRowsProps {
  readonly rows: readonly LabelledRow[];
  /** Names the list for a reader who reaches it by landmark rather than by reading down the panel. */
  readonly label?: string | undefined;
}

export function ReasonRows({ rows, label }: ReasonRowsProps) {
  if (rows.length === 0) return null;

  return (
    <dl className="reason-rows" aria-label={label}>
      {rows.map((row) => (
        <div className="contents" key={`${row.label}:${row.value}`}>
          <dt className="reason-rows__label">{row.label}</dt>
          <dd className="reason-rows__value">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
