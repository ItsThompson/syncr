/* A WIRE BLOCK, REDUCED TO WHAT THE GRID DRAWS IT FROM.
 *
 * The kit knows what a Block is and does not know what a response is, so the narrowing happens here, at the
 * boundary, once. Three fields need a lookup rather than a copy.
 *
 * THE AREA IS RESOLVED TO A RAMP STEP AND A NAME, and both travel. Past twelve Areas the ramp repeats, and the
 * wire carries the STEP rather than the deal, so two Areas can hold one pigment and a chip alone stops
 * identifying anything. The name is what separates them, which is why no block reaches the grid with a pigment
 * and no name.
 *
 * A BLOCK WITH NO AREA IS THE FRAME AND THE IMPORTED ANCHOR. One defines how much time exists and the other is
 * time the product does not own, so neither has an Area to be charged to and neither takes a pigment. The top
 * rule says which of the two it is.
 *
 * A DIVIDED TASK'S `N OF M` PAIR IS NOT READ HERE. `splitCount` is the number of POSITIONS a division occupies
 * rather than the number of pieces the document holds, and a pin on a high chunk makes the two differ: a task
 * holding three pieces can carry a count of six. Rendering the pair before that is settled would put a figure on
 * the grid that a reader cannot reconcile with what they can see. */

import { areaPigment } from "../../ui/domain";
import type { GridBlock } from "../../ui/domain";
import type { components } from "../../api/schema";

type BlockResponse = components["schemas"]["BlockResponse"];
type AreaResponse = components["schemas"]["AreaResponse"];

/** A block before it is placed in a column: the instants it covers, and the facts the grid draws. */
export interface WeekBlock extends Omit<GridBlock, "span"> {
  readonly startMs: number;
  readonly endMs: number;
}

/** The Areas a block can be charged to, by identifier, which is a name and a step each. */
export type AreaIndex = ReadonlyMap<string, AreaResponse>;

export function areaIndexOf(areas: readonly AreaResponse[]): AreaIndex {
  return new Map(areas.map((area) => [area.id, area]));
}

export function weekBlockOf(block: BlockResponse, areas: AreaIndex): WeekBlock {
  const area = block.areaId === null ? undefined : areas.get(block.areaId);
  return {
    id: block.id,
    title: block.title,
    origin: block.origin,
    pigment: area === undefined ? null : areaPigment(area.pigmentIndex),
    areaName: area?.name ?? null,
    isPinned: block.pinned,
    startMs: Date.parse(block.interval.start),
    endMs: Date.parse(block.interval.end),
  };
}
