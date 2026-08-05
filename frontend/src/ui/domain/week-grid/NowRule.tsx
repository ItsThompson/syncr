/* THE NOW RULE. A 2px line across the day column at the current minute.
 *
 * THIS IS THE ONLY MARKER OF WHAT IS PAST. Past blocks take no channel of their own, because the rule already
 * says where the boundary is and immutability is not a per-block property worth a pigment. That is one of the
 * four meanings deliberately moved off the block rather than given a fifth channel.
 *
 * The reading itself sits in the axis gutter rather than on the line, because a time on the line would collide
 * with whatever block the line crosses, and the axis is the one column that has room for it. `TimeAxis` draws
 * that half. */

import "./grid.css";

export interface NowRuleProps {
  /** Where the current minute falls on the canvas. */
  readonly topPx: number;
}

const PLACES = 3;

export function NowRule({ topPx }: NowRuleProps) {
  return (
    <div aria-hidden="true" className="week-now" style={{ top: `${topPx.toFixed(PLACES)}px` }} />
  );
}
