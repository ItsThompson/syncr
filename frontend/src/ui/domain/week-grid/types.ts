/* WHAT THE GRID RENDERS, which is not what the wire sends.
 *
 * The wire sends instants. The grid draws seven columns, and a block's position inside one is its distance
 * from THAT COLUMN'S own start, in minutes, taken between instants. Those minutes are the one representation
 * every other module here works in, and computing them once is what makes a 23-hour day and a 25-hour day
 * need no special case: the subtraction is between two instants, so an hour that does not exist is simply not
 * in the difference.
 *
 * A MINUTE OFFSET MAY BE NEGATIVE AND MAY EXCEED A DAY. A frame occurrence beginning at 23:00 on Sunday ends
 * inside Monday, and it is a block of the week its start falls in. Monday's column therefore draws a span that
 * starts before Monday did. Clamping it to zero would hide a real seven hours of occupied time, which is the
 * class of defect the axis rule exists to prevent. */

import type { AreaPigment, BlockOrigin } from "../marks";

/** A half-open interval of instants, in epoch milliseconds, as `[startMs, endMs)`. */
export interface Instants {
  readonly startMs: number;
  readonly endMs: number;
}

/**
 * A span in minutes from a day column's own start.
 *
 * Half-open like the instants it came from, so a block ending at 09:00 and one beginning there do not overlap.
 */
export interface OffsetSpan {
  readonly startMin: number;
  readonly endMin: number;
}

/** The four heights a block's title degrades through. The block degrades; the axis does not. */
export type BlockTier = "label" | "compact" | "sliver" | "hairline";

/**
 * Why a band is drawn instead of a block. It changes no pixel: it is what a test and a reader key on.
 *
 * A hand-written copy of two server enums, `ForbiddenKind` and `EmptySlotReason`, because the generated
 * payload types are assigned into it. Widening either of those without widening this is a compile error at
 * the assignment in `routes/week/bands.ts` rather than a silent divergence.
 */
export type BandReason =
  | "recovery"
  | "prep_unattributed"
  | "transit_unattributed"
  | "off_plan"
  | "no_eligible_content"
  | "blocked_by_constraint"
  | "not_solved"
  | "elapsed";

/** One thing that happens in the week, reduced to what the grid draws it from. */
export interface GridBlock {
  readonly id: string;
  readonly title: string;
  readonly span: OffsetSpan;
  readonly origin: BlockOrigin;
  /** The Area's ramp step, or null for the frame and for an imported anchor, which hold no Area. */
  readonly pigment: AreaPigment | null;
  /** The Area's name, which is what identifies it wherever the step's ink cannot. */
  readonly areaName: string | null;
  /** The user's own edit. A block fixed by derivation is not pinned. */
  readonly isPinned: boolean;
}

/** A span nothing may fill, or nothing did. One drawing rule for all three of the kinds that produce one. */
export interface GridBand {
  readonly id: string;
  readonly span: OffsetSpan;
  /** What the gutter says, or null for a declared off-plan span the user gave no word for. */
  readonly label: string | null;
  readonly reason: BandReason;
}

/** One day column: what it holds, and the instant its own axis starts at. */
export interface WeekDay {
  /** `YYYY-MM-DD`, the key the week's zone map is written against. */
  readonly date: string;
  /** The zone in force on this date, which is what its own start instant was resolved in. */
  readonly zone: string;
  /** The instant local midnight fell at, which every offset in this column is measured from. */
  readonly startMs: number;
  /** How long the local day runs, from instants: 1380, 1440 or 1500 minutes. */
  readonly minutes: number;
  readonly blocks: readonly GridBlock[];
  readonly bands: readonly GridBand[];
}

/**
 * The axis window, in minutes from each column's own start.
 *
 * One window for all seven columns, so an hour label lines up across the week. It is the union of the user's
 * declared day bounds and the bounding span of every block and band in the visible week, which is why a block
 * outside the bounds widens the axis rather than being cropped by it.
 */
export interface Extent {
  readonly startMin: number;
  readonly endMin: number;
}
