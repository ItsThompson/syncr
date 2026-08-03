/* A labelled figure: one of the three readings in the summary strip, or a cell in a review.
 *
 * The figure arrives already formatted, because how a duration or a percentage reads is a domain decision and
 * this cell is a container. What it owns is that the figure sets in mono with tabular figures and never in the
 * serif, which is the rule the design language states for every headline number in the product. */

import type { ReactNode } from "react";

import "./StatCell.css";

export interface StatCellProps {
  /** The eyebrow above the figure, rendered uppercase and tracked out. */
  readonly label: string;
  /** Already formatted: `91`, `7h 15m`, `+4%`. */
  readonly figure: ReactNode;
  /** A qualifier under the figure, such as the word that says the plan is still solving. */
  readonly sub?: string | undefined;
}

export function StatCell({ label, figure, sub }: StatCellProps) {
  return (
    <div className="stat-cell">
      <p className="stat-cell__label">{label}</p>
      <p className="stat-cell__figure">{figure}</p>
      {sub === undefined ? null : <p className="stat-cell__sub">{sub}</p>}
    </div>
  );
}
