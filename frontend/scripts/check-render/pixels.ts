/* READING A SCREENSHOT AS ROWS OF INK.
 *
 * The question every case asks is whether two renderings of one title agree over the line boxes both show. A pixel
 * comparison answers it directly and needs no font metrics, no glyph table and no text extraction: an ellipsis is
 * ink where the other rendering has none, and a mid-glyph clip is ink the other rendering has more of.
 *
 * THE COMPARISON IS ANCHORED ON THE FIRST INKED ROW rather than on arithmetic over borders and padding. Aligning by
 * computed offsets would make the check depend on the same declarations it exists to look past, and it would move
 * every time a padding token did. The first row that holds ink is where the text starts, whatever put it there.
 *
 * `decodeToGray` is the plate generator's own decoder, reused rather than re-implemented: it already composites
 * alpha over paper, which is what makes a transparent screenshot background read as white instead of as ink. */

import { decodeToGray, type GrayImage } from "../generate-plate/png.ts";

/** Above this is paper, below it is ink. Chromium antialiases, so the threshold sits well clear of both. */
const INK_BELOW = 200;

export interface Region {
  readonly xPx: number;
  readonly widthPx: number;
  readonly topPx: number;
  readonly heightPx: number;
}

export function imageOf(bytes: Buffer): GrayImage {
  return decodeToGray(bytes);
}

/** One row of a region, as its luminance bytes. */
function row(image: GrayImage, region: Region, y: number): Uint8Array {
  const from = (region.topPx + y) * image.width + region.xPx;
  return image.gray.subarray(from, from + region.widthPx);
}

function hasInk(pixels: Uint8Array): boolean {
  return pixels.some((value) => value < INK_BELOW);
}

/**
 * The first row of a region that holds any ink, or null where the region is blank.
 *
 * Null is a finding rather than a zero: a case whose block rendered nothing at all would otherwise compare blank
 * against blank and pass, which is the shape of a guard that cannot fail.
 */
export function firstInkedRow(image: GrayImage, region: Region): number | null {
  for (let y = 0; y < region.heightPx; y += 1) {
    if (hasInk(row(image, region, y))) return y;
  }
  return null;
}

export interface RowDifference {
  /** Rows below the first inked one, so a reader can find the line it lands in. */
  readonly atRow: number;
  readonly differingPixels: number;
}

/**
 * Where two regions disagree over `depthPx` rows, each anchored on its own first inked row.
 *
 * Empty means the two renderings are identical over the rows compared, which for a clamped title against an
 * unclamped one is the whole of "the clip lands on a line boundary and adds nothing".
 */
export function differencesBetween(
  image: GrayImage,
  left: Region,
  right: Region,
  depthPx: number,
): RowDifference[] {
  const leftTop = firstInkedRow(image, left);
  const rightTop = firstInkedRow(image, right);
  if (leftTop === null || rightTop === null) {
    return [{ atRow: 0, differingPixels: left.widthPx }];
  }

  const found: RowDifference[] = [];
  for (let y = 0; y < depthPx; y += 1) {
    const leftRow = row(image, { ...left, topPx: left.topPx + leftTop }, y);
    const rightRow = row(image, { ...right, topPx: right.topPx + rightTop }, y);
    let differing = 0;
    for (let x = 0; x < Math.min(leftRow.length, rightRow.length); x += 1) {
      if (leftRow[x] !== rightRow[x]) differing += 1;
    }
    if (differing > 0) found.push({ atRow: y, differingPixels: differing });
  }
  return found;
}

/** A region rendered as one character per pixel, so a finding can show what it saw. */
export function sketch(image: GrayImage, region: Region, depthPx: number): string[] {
  const top = firstInkedRow(image, region) ?? 0;
  const lines: string[] = [];
  for (let y = 0; y < depthPx; y += 1) {
    const pixels = row(image, { ...region, topPx: region.topPx + top }, y);
    lines.push([...pixels].map((value) => (value < 128 ? "#" : value < 240 ? "+" : ".")).join(""));
  }
  return lines;
}
