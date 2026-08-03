/* A single-figure surface: one reading, in the bordered block every other surface uses.
 *
 * It is a `Panel` wrapping one `StatCell` rather than a second bordered box, which is what keeps one
 * definition of the block's border in the layer. What this component adds is the pairing itself: a card is
 * ONE figure with a footer, so a screen cannot quietly grow a card into a panel with three of them. */

import type { ReactNode } from "react";

import { Panel } from "./Panel";
import { StatCell } from "./StatCell";

export interface CardProps {
  /** The eyebrow above the figure. */
  readonly label: string;
  /** Already formatted, because how a figure reads is a domain decision. */
  readonly figure: ReactNode;
  /** A qualifier under the figure. */
  readonly sub?: string | undefined;
  /** The footnote under the hairline: what the figure is measured against, or when it was taken. */
  readonly footer?: ReactNode;
}

export function Card({ label, figure, sub, footer }: CardProps) {
  return (
    <Panel footer={footer}>
      <StatCell label={label} figure={figure} sub={sub} />
    </Panel>
  );
}
