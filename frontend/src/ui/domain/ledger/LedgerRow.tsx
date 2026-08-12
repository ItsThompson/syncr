/* One ledger row: a time range, its duration, the Area, the title, and whatever the reader can do about it.
 *
 * THE OUTCOME CONTROLS ARRIVE AS CHILDREN. Skip, partial with a minutes stepper, and moved with a time-range
 * control are five states and three controls wired to a mutation, which is the Today screen's work rather than
 * this row's. What the row owns is that they land in a slot at a fixed offset, so a reader's pointer finds the
 * same control in every row.
 *
 * THE TIME AND THE DURATION ARRIVE FORMATTED. How an interval reads depends on the reader's home zone or their
 * travel override, which the domain knows and a row does not: a row that formatted an instant would be a row no
 * test could pin to a zone. The same rule makes today a prop on the calendar.
 *
 * The Area is passed as its name and its ramp step rather than as a chip, so the row cannot be given a chip
 * without one. `AreaChip` refuses that at the typecheck; passing the pair keeps the refusal one hop closer to the
 * data. A routine carries no Area at all, and its column is simply empty.
 *
 * THE BORDERED BOX AROUND A RUN OF ROWS IS THE CALLER'S `Panel`. A row draws itself and its hairline; the block's
 * border and raised fill keep the one definition the layout layer gives them.
 *
 * THE CURRENT ROW'S MARK IS THE KIT'S ONE ASSIGNMENT. The row sets `data-current` and `states.css` says what it
 * looks like, for every row-shaped surface at once. A screen declaring the fill and the left rule itself is the
 * drift `scripts/check-channels` refuses. */

import type { ReactNode } from "react";

import { Gutter } from "../../layout";
import "../../primitives/states.css";
import { AreaChip, type AreaPigment } from "../marks";
import "./ledger.css";

export interface LedgerRowArea {
  readonly name: string;
  /** From `areaPigment(area.pigmentIndex)`. */
  readonly pigment: AreaPigment;
}

export interface LedgerRowProps {
  /** Already formatted in the reader's zone: `13:30-17:00`. */
  readonly timeRange: string;
  /** Already formatted: `3h 30m`, or `210m` where the ledger counts minutes. */
  readonly duration: string;
  readonly title: string;
  /** Absent for a routine, which carries no Area and therefore no pigment. */
  readonly area?: LedgerRowArea | undefined;
  /** A `GlyphSlot`, where the row carries a mark. The column is reserved either way. */
  readonly mark?: ReactNode;
  /** The row cursor's position. At most one row in a ledger carries it. */
  readonly isCurrent?: boolean | undefined;
  /** The outcome controls, wired by the screen that owns the mutation. */
  readonly children?: ReactNode;
}

export function LedgerRow({
  timeRange,
  duration,
  title,
  area,
  mark,
  isCurrent,
  children,
}: LedgerRowProps) {
  return (
    <div className="state-row ledger__row" data-current={isCurrent === true ? "" : undefined}>
      <Gutter>{mark}</Gutter>
      <span className="ledger__time">{timeRange}</span>
      <span className="ledger__duration">{duration}</span>
      <span className="ledger__area">
        {area === undefined ? null : <AreaChip name={area.name} pigment={area.pigment} />}
      </span>
      <span className="ledger__title">{title}</span>
      <span className="ledger__outcome">{children}</span>
    </div>
  );
}
