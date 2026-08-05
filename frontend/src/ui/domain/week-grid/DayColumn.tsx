/* ONE DAY COLUMN, AND THE OVERLAP LAYOUT IT OWNS.
 *
 * Overlap is computed per column, from the column's own block list, because two blocks in different columns
 * cannot overlap and a week-wide sweep would have to partition by day first anyway. The sweep is in
 * `overlap.ts` and it is handed SPANS rather than blocks, so no origin can be special-cased: the circadian frame
 * participates exactly like anything else, which is what an earlier full-width-backdrop draft got wrong twice.
 *
 * Z-ORDER IS THE ONE THING THIS COMPONENT DECIDES, and it decides it by position in the markup rather than by
 * reasoning: the bands first, so every block sits above them; then the blocks; then the now rule, which is a
 * statement about all of them. The overlap layout does not depend on any of it. */

import { boxOf } from "./geometry";
import { placeOverlaps } from "./overlap";
import { Block } from "./Block";
import { ForbiddenBand } from "./ForbiddenBand";
import { GridLines } from "./GridLines";
import { NowRule } from "./NowRule";
import type { Extent, WeekDay } from "./types";
import "./grid.css";

export interface DayColumnProps {
  readonly day: WeekDay;
  /** What the column is called in the header, already formatted. */
  readonly label: string;
  readonly extent: Extent;
  readonly pxPerMin: number;
  readonly canvasHeightPx: number;
  /** Where the current minute falls in THIS column, or null when now is not inside it. */
  readonly nowMin: number | null;
}

const PLACES = 3;

export function DayColumn({
  day,
  label,
  extent,
  pxPerMin,
  canvasHeightPx,
  nowMin,
}: DayColumnProps) {
  const across = placeOverlaps(day.blocks.map((block) => block.span));

  return (
    <div className="week-day max-narrow:shrink-0 max-narrow:grow-0 max-narrow:basis-col-min">
      <div className="week-day__head">
        {label}
        <span className="week-day__count">{day.blocks.length}</span>
      </div>
      <div className="week-day__canvas" style={{ height: `${canvasHeightPx.toFixed(PLACES)}px` }}>
        <GridLines extent={extent} pxPerMin={pxPerMin} />
        {day.bands.map((band) => (
          <ForbiddenBand key={band.id} label={band.label} {...boxOf(band.span, extent, pxPerMin)} />
        ))}
        {day.blocks.map((block, index) => (
          <Block
            block={block}
            key={block.id}
            placement={{ ...boxOf(block.span, extent, pxPerMin), across: across[index] }}
          />
        ))}
        {nowMin === null ? null : <NowRule topPx={(nowMin - extent.startMin) * pxPerMin} />}
      </div>
    </div>
  );
}
