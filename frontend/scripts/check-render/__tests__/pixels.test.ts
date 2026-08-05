/* THE RENDERED-PIXEL GATE'S OWN TESTS.
 *
 * Two claims, and the second is the one that matters. THE PIXEL READERS DO WHAT THEY SAY, asserted over synthetic
 * images so a failure here is about the reader rather than about a browser. And THE PROBE RENDERS WHAT THE COMPONENT
 * RENDERS: the page is built from a copy of `Block.tsx`'s markup, so a change to the component that the probe does
 * not follow would leave the gate measuring something the product does not ship. That is the drift a probe is
 * always one edit away from, and it is checked by rendering the real component and comparing.
 *
 * The browser itself is not exercised here. A gate that needs a browser is run by `npm run lint:render`, and what a
 * unit test can hold is everything either side of it.
 *
 * THE PROBE'S FIDELITY TO THE COMPONENT is asserted beside the component, in
 * `src/ui/domain/week-grid/__tests__/probe.test.tsx`, because it is a claim about what `Block` renders and it needs
 * JSX, which the script suite's own file pattern does not take. */

import { describe, expect, it } from "vitest";

import { CASES, geometryOf, heightOf, linesOf } from "../page.ts";
import { differencesBetween, firstInkedRow, imageOf, sketch, type Region } from "../pixels.ts";

/** A gray image the readers can be pointed at, without a PNG codec in the way. */
function gray(width: number, rows: readonly string[]) {
  const bytes = new Uint8Array(width * rows.length);
  for (const [y, row] of rows.entries()) {
    for (let x = 0; x < width; x += 1) bytes[y * width + x] = row[x] === "#" ? 0 : 255;
  }
  return { width, height: rows.length, gray: bytes };
}

const WHOLE: Region = { xPx: 0, widthPx: 6, topPx: 0, heightPx: 6 };

describe("the first inked row", () => {
  it("is the first row holding any ink at all", () => {
    const image = gray(6, ["......", "......", "..##..", "......"]);

    expect(firstInkedRow(image, { ...WHOLE, heightPx: 4 })).toBe(2);
  });

  it("is null for a blank region, so a case that rendered nothing cannot pass", () => {
    const image = gray(6, ["......", "......"]);

    expect(firstInkedRow(image, { ...WHOLE, heightPx: 2 })).toBeNull();
  });
});

describe("the difference between two regions", () => {
  /* Each region is anchored on its OWN first inked row, so a vertical offset between the two renderings is not read
   * as a difference. What is being compared is the glyphs, not where the box that holds them starts. */
  it("is empty where the two hold the same ink at different offsets", () => {
    const image = gray(6, ["..##..", "......", "......", "..##..", "......"]);
    const left: Region = { xPx: 0, widthPx: 6, topPx: 0, heightPx: 3 };
    const right: Region = { xPx: 0, widthPx: 6, topPx: 3, heightPx: 2 };

    expect(differencesBetween(image, left, right, 1)).toEqual([]);
  });

  it("names the row and the count where they disagree", () => {
    const image = gray(6, ["..###.", "..##..", "......"]);
    const left: Region = { xPx: 0, widthPx: 6, topPx: 0, heightPx: 1 };
    const right: Region = { xPx: 0, widthPx: 6, topPx: 1, heightPx: 1 };

    expect(differencesBetween(image, left, right, 1)).toEqual([{ atRow: 0, differingPixels: 1 }]);
  });

  it("reports a blank region as a whole-width difference rather than as agreement", () => {
    const image = gray(6, ["..##..", "......"]);
    const left: Region = { xPx: 0, widthPx: 6, topPx: 0, heightPx: 1 };
    const blank: Region = { xPx: 0, widthPx: 6, topPx: 1, heightPx: 1 };

    expect(differencesBetween(image, left, blank, 1)).toEqual([{ atRow: 0, differingPixels: 6 }]);
  });

  it("sketches a region so a finding can show what it saw", () => {
    const image = gray(4, ["..#.", "#...."]);

    expect(sketch(image, { xPx: 0, widthPx: 4, topPx: 0, heightPx: 2 }, 1)).toEqual(["..#."]);
  });

  it("decodes a PNG through the plate generator's own reader", () => {
    /* A one-pixel 8-bit greyscale PNG, so the decoder is exercised rather than assumed present. */
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgABSK+kcQAAAABJRU5ErkJggg==",
      "base64",
    );

    expect(imageOf(png).width).toBe(1);
  });
});

describe("the case geometry", () => {
  it("takes each height from the reference display and each line count from the ladder", () => {
    expect(heightOf(30, 12)).toBeCloseTo(26.083, 3);
    expect(linesOf(heightOf(30, 12))).toBe(1);
    expect(linesOf(heightOf(90, 12))).toBe(5);
    expect(linesOf(heightOf(15, 12))).toBe(1);
  });

  it("renders each case twice, capped and uncapped, at its own place on the page", () => {
    const cases = geometryOf(CASES);

    for (const each of cases) expect(each.uncappedTopPx).toBeGreaterThan(each.cappedTopPx);
    expect(new Set(cases.map((each) => each.cappedTopPx)).size).toBe(cases.length);
  });
});
