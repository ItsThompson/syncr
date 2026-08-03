/* The column at the head of a row that hosts an adornment: an Area chip, a glyph, a mark.
 *
 * It is rendered whether or not there is anything in it, because the column is what makes a ledger's titles
 * start at one offset. A row that skipped the empty gutter would set its title 20px to the left of its
 * neighbour's and read as a rendering fault. */

import type { ReactNode } from "react";

import "./Gutter.css";

export interface GutterProps {
  /** The adornment. Absent leaves the column reserved and empty, which is the common case in a ledger. */
  readonly children?: ReactNode;
}

export function Gutter({ children }: GutterProps) {
  return <div className="gutter">{children}</div>;
}
