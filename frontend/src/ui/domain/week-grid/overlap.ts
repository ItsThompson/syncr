/* OVERLAP: A SWEEP, THEN COLUMNS. No special case for any origin.
 *
 *   1  sort by start, then by descending end
 *   2  cluster by a running maximum end: a block joins the current cluster when its start is BEFORE the
 *      cluster's running maximum end
 *   3  within a cluster, give each block the LEFTMOST column whose last block has already finished
 *   4  depth 1 to 3      -> an even split across the cluster's column count
 *      depth 4 and above -> a stagger: later start in front, at a fixed indent, plus a count marker in the
 *                           frontmost block
 *
 * NO ORIGIN IS SPECIAL-CASED. An earlier draft made the circadian frame a full-width backdrop that never
 * split, and it was wrong twice: `Wake Up` is origin `frame` and is a genuine fifteen-minute participant, and a
 * full-width frame block painted over whatever it overlapped and clipped that block's title. The frame
 * participates exactly like anything else, and this module is handed spans rather than blocks so it could not
 * tell one origin from another if it wanted to.
 *
 * LAYOUT DOES NOT DEPEND ON PAINT ORDER. The even split is disjoint, so it needs no stacking at all, and the
 * stagger's layer is a function of the column a block was already given. Nothing here reasons about z-index to
 * decide where a box goes, which is what leaves the grid with no magic threshold to tune.
 *
 * EVEN SPLITTING STOPS AT DEPTH 3, because an even fifth of a 137px column is 27px, and 27px holds no title at
 * any tier. */

import { OVERLAP_MAX_SPLIT } from "./metrics";
import type { OffsetSpan } from "./types";

/** Where a block sits across its column's width, and what it has to say about what is behind it. */
export interface Placement {
  /** Fraction of the column's width between the column's left edge and the block's, 0 to 1. */
  readonly left: number;
  /** Fraction between the block's right edge and the column's, 0 to 1. */
  readonly right: number;
  /** How many `--overlap-indent` steps in from the left the block starts. Zero below depth 4. */
  readonly indentSteps: number;
  /** Paint order inside the cluster. Only a stagger needs one; an even split is disjoint. */
  readonly layer: number;
  /** How many blocks are staggered behind this one, or null when it is not the frontmost. */
  readonly overlapCount: number | null;
  /** True when the block no longer meets the column's left edge, so it needs a rule to divide it. */
  readonly isSplit: boolean;
}

interface Indexed {
  readonly index: number;
  readonly span: OffsetSpan;
}

/** One run of blocks that overlap transitively, and the columns they were dealt. */
interface Cluster {
  readonly members: Indexed[];
  readonly columnOf: Map<number, number>;
  readonly columns: number;
}

/**
 * Where each span sits across its column, in the order the spans were given.
 *
 * The sweep works on a sorted copy and every result is written back to the caller's index, so a caller may keep
 * its blocks in any order it likes: sorting here and returning a sorted list would make the answer depend on an
 * order the caller cannot see.
 */
export function placeOverlaps(spans: readonly OffsetSpan[]): Placement[] {
  /* Collected into a map and then materialised in the caller's own order, so the returned array is never a typed
   * array with holes in it: every span joins exactly one cluster, and a `Placement[]` seeded with `undefined` would
   * assert that before the sweep has proved it. */
  const byIndex = new Map<number, Placement>();
  for (const cluster of clustersOf(spans)) {
    for (const member of cluster.members) {
      byIndex.set(member.index, placementIn(cluster, member));
    }
  }
  return spans.map((_, index) => byIndex.get(index) ?? WHOLE_COLUMN);
}

/* What a span gets when no cluster claimed it, which the sweep makes unreachable: a span is compared against a
 * running maximum end and joins the current cluster or opens one, so there is no third path. It is a value rather
 * than a throw because a grid that drew one block full width would be a better failure than a grid that drew none. */
const WHOLE_COLUMN: Placement = {
  left: 0,
  right: 0,
  indentSteps: 0,
  layer: 0,
  overlapCount: null,
  isSplit: false,
};

/* Sorted by start, then by DESCENDING end, so the longest of several blocks beginning together is dealt the
 * leftmost column and the shorter ones stack to its right. The reverse leaves a long block sitting right of the
 * short ones it contains, which reads as unrelated rather than as an overlap. */
function sorted(spans: readonly OffsetSpan[]): Indexed[] {
  return spans
    .map((span, index) => ({ index, span }))
    .toSorted(
      (left, right) =>
        left.span.startMin - right.span.startMin || right.span.endMin - left.span.endMin,
    );
}

function clustersOf(spans: readonly OffsetSpan[]): Cluster[] {
  const clusters: Cluster[] = [];
  let members: Indexed[] = [];
  let runningMaxEnd = Number.NEGATIVE_INFINITY;

  for (const member of sorted(spans)) {
    /* Strictly before, because the spans are half-open: a block ending at 09:00 and one beginning at 09:00
     * share no minute, so they are two clusters of one rather than one cluster of two. */
    if (members.length > 0 && member.span.startMin >= runningMaxEnd) {
      clusters.push(dealColumns(members));
      members = [];
      runningMaxEnd = Number.NEGATIVE_INFINITY;
    }
    members.push(member);
    runningMaxEnd = Math.max(runningMaxEnd, member.span.endMin);
  }
  if (members.length > 0) clusters.push(dealColumns(members));
  return clusters;
}

/** The leftmost column whose last block has already finished, per member, in sweep order. */
function dealColumns(members: Indexed[]): Cluster {
  const lastEnd: number[] = [];
  const columnOf = new Map<number, number>();

  for (const member of members) {
    let column = lastEnd.findIndex((end) => end <= member.span.startMin);
    if (column === -1) {
      column = lastEnd.length;
      lastEnd.push(member.span.endMin);
    } else lastEnd[column] = Math.max(lastEnd[column], member.span.endMin);
    columnOf.set(member.index, column);
  }
  return { members, columnOf, columns: lastEnd.length };
}

function placementIn(cluster: Cluster, member: Indexed): Placement {
  const column = cluster.columnOf.get(member.index) ?? 0;
  const columns = cluster.columns;

  if (columns <= OVERLAP_MAX_SPLIT) {
    return {
      left: column / columns,
      right: (columns - 1 - column) / columns,
      indentSteps: 0,
      layer: 0,
      overlapCount: null,
      isSplit: column > 0,
    };
  }

  /* The stagger. Every block reaches the column's right edge and each is indented past the one behind it, so
   * the later start is in front and the earlier one is still readable to its left. The count rides in the
   * frontmost block, which is the only one whose neighbours are entirely hidden behind it. */
  const isFrontmost = column === columns - 1;
  return {
    left: 0,
    right: 0,
    indentSteps: column,
    layer: column + 1,
    overlapCount: isFrontmost ? columns : null,
    isSplit: column > 0,
  };
}
