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

/**
 * One row of a region, as its luminance bytes, or null where the row is outside it.
 *
 * NULL RATHER THAN THE NEIGHBOUR'S PIXELS. The first version computed an offset and read whatever was there, so a
 * comparison deeper than its own region silently read the copy below it and then the next case: a fourteen-line case
 * reported 1775 differing pixels, every one of them spurious. An out-of-region read is now a fact a caller has to
 * handle rather than a plausible answer.
 */
function row(image: GrayImage, region: Region, y: number): Uint8Array | null {
  if (y < 0 || y >= region.heightPx) return null;
  if (region.topPx + y >= image.height) return null;
  const from = (region.topPx + y) * image.width + region.xPx;
  return image.gray.subarray(from, from + Math.min(region.widthPx, image.width - region.xPx));
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
    const pixels = row(image, region, y);
    if (pixels !== null && hasInk(pixels)) return y;
  }
  return null;
}

/** The last column of a region's row that holds ink, or null where the row is blank. */
export function lastInkedColumn(image: GrayImage, region: Region, y: number): number | null {
  const pixels = row(image, region, y);
  if (pixels === null) return null;
  for (let x = pixels.length - 1; x >= 0; x -= 1) {
    if (pixels[x] < INK_BELOW) return x;
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
 * Empty means the two renderings are identical over the rows compared. The depth is CLAMPED to what both regions
 * hold, because a comparison that walks past a region is not a comparison: it reads the copy below.
 */
export function differencesBetween(
  image: GrayImage,
  left: Region,
  right: Region,
  depthPx: number,
  widthPx: number = left.widthPx,
): RowDifference[] {
  const leftTop = firstInkedRow(image, left);
  const rightTop = firstInkedRow(image, right);
  if (leftTop === null || rightTop === null) {
    return [{ atRow: 0, differingPixels: left.widthPx }];
  }

  const found: RowDifference[] = [];
  const depth = Math.min(depthPx, left.heightPx - leftTop, right.heightPx - rightTop);
  for (let y = 0; y < depth; y += 1) {
    const leftRow = row(image, { ...left, widthPx }, leftTop + y);
    const rightRow = row(image, { ...right, widthPx }, rightTop + y);
    if (leftRow === null || rightRow === null) break;
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
  for (let y = 0; y < Math.min(depthPx, region.heightPx - top); y += 1) {
    const pixels = row(image, region, top + y);
    if (pixels === null) break;
    lines.push([...pixels].map((value) => (value < 128 ? "#" : value < 240 ? "+" : ".")).join(""));
  }
  return lines;
}
