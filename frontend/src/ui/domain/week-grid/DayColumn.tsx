/* ONE DAY COLUMN, AND THE OVERLAP LAYOUT IT OWNS.
 *
 * Overlap is computed per column, from the column's own block list, because two blocks in different columns
 * cannot overlap and a week-wide sweep would have to partition by day first anyway. The sweep is in
 * `overlap.ts` and it is handed SPANS rather than blocks, so no origin can be special-cased: the circadian frame
 * participates exactly like anything else, which is what an earlier full-width-backdrop draft got wrong twice.
 *
 * Z-ORDER IS THE ONE THING THIS COMPONENT DECIDES, and it decides it by position in the markup rather than by
 * reasoning: the bands first, so every block sits above them; then the blocks; then the now rule and the insertion
 * marker, which are statements about all of them. The overlap layout does not depend on any of it.
 *
 * THE CANVAS IS HANDED TO A DRAG RATHER THAN FOUND BY ONE. A pointer position becomes a minute through this box, so
 * the element travels with the pointerdown instead of being located from the event's ancestors: a drag that read the
 * DOM upwards would depend on markup this component is free to change.
 *
 * A DRAG BEGINS ON THE PRIMARY BUTTON AND CAPTURES THE POINTER. Both are here rather than in the drag itself,
 * because both are facts about the EVENT this column received: the drag reads positions, and it never sees the
 * element the press landed on. */

import { useRef } from "react";

import { boxOf } from "./geometry";
import { placeOverlaps } from "./overlap";
import { Block, type BlockStates } from "./Block";
import { ForbiddenBand } from "./ForbiddenBand";
import { GridLines } from "./GridLines";
import { InsertionMarker } from "./InsertionMarker";
import { NowRule } from "./NowRule";
import type { DragOrigin } from "./useDiscreteDrag";
import type { Extent, GridBlock, WeekDay } from "./types";
import "./grid.css";

/** What a column needs from whatever owns interaction. Absent throughout leaves the column read-only. */
export interface ColumnInteraction {
  /** The states one block is in, which the column does not decide and does not remember. */
  readonly statesOf?: ((blockId: string) => BlockStates) | undefined;
  readonly onSelect?: ((blockId: string) => void) | undefined;
  readonly onDragBegin?: ((origin: DragOrigin) => void) | undefined;
  /** Activating a band's gutter label, which is how an empty slot becomes an invitation. */
  readonly onBandActivate?: ((bandId: string) => void) | undefined;
}

export interface DayColumnProps {
  readonly day: WeekDay;
  /** What the column is called in the header, already formatted. */
  readonly label: string;
  readonly extent: Extent;
  readonly pxPerMin: number;
  readonly canvasHeightPx: number;
  /** Where the current minute falls in THIS column, or null when now is not inside it. */
  readonly nowMin: number | null;
  /** Where the drag's hairline sits in THIS column, in the column's own minutes, or null. */
  readonly insertionMin?: number | null | undefined;
  readonly interaction?: ColumnInteraction | undefined;
}

const PLACES = 3;
const NO_INTERACTION: ColumnInteraction = {};

export function DayColumn({
  day,
  label,
  extent,
  pxPerMin,
  canvasHeightPx,
  nowMin,
  insertionMin = null,
  interaction = NO_INTERACTION,
}: DayColumnProps) {
  const across = placeOverlaps(day.blocks.map((block) => block.span));
  const canvas = useRef<HTMLDivElement>(null);

  return (
    <div className="week-day max-narrow:shrink-0 max-narrow:grow-0 max-narrow:basis-col-min">
      <div className="week-day__head">
        {label}
        <span className="week-day__count">{day.blocks.length}</span>
      </div>
      <div
        className="week-day__canvas"
        ref={canvas}
        style={{ height: `${canvasHeightPx.toFixed(PLACES)}px` }}
      >
        <GridLines extent={extent} pxPerMin={pxPerMin} />
        {day.bands.map((band) => (
          <ForbiddenBand
            key={band.id}
            label={band.label}
            onActivate={
              interaction.onBandActivate === undefined
                ? undefined
                : () => {
                    interaction.onBandActivate?.(band.id);
                  }
            }
            {...boxOf(band.span, extent, pxPerMin)}
          />
        ))}
        {day.blocks.map((block, index) => (
          <Block
            block={block}
            key={block.id}
            onPointerDown={(event) => {
              /* THE PRIMARY BUTTON ONLY. A secondary-button press opens a context menu and delivers no release the
               * page can pair with it, so a drag begun on one is a drag that stays live. */
              if (event.button !== 0) return;
              /* CAPTURED, so a release anywhere reaches this drag. Without it a mouse released outside the viewport
               * delivers no `pointerup` to the page and the drag never ends. */
              event.currentTarget.setPointerCapture(event.pointerId);
              interaction.onDragBegin?.(originOf(block, day, canvas.current, event.clientY));
            }}
            onSelect={() => {
              interaction.onSelect?.(block.id);
            }}
            placement={{ ...boxOf(block.span, extent, pxPerMin), across: across[index] }}
            states={interaction.statesOf?.(block.id)}
          />
        ))}
        {nowMin === null ? null : <NowRule topPx={(nowMin - extent.startMin) * pxPerMin} />}
        {insertionMin === null ? null : (
          <InsertionMarker
            atMin={insertionMin}
            topPx={(insertionMin - extent.startMin) * pxPerMin}
          />
        )}
      </div>
    </div>
  );
}

function originOf(
  block: GridBlock,
  day: WeekDay,
  canvas: HTMLElement | null,
  pointerY: number,
): DragOrigin {
  return {
    blockId: block.id,
    date: day.date,
    fromMin: block.span.startMin,
    dayStartMs: day.startMs,
    canvas,
    pointerY,
  };
}
