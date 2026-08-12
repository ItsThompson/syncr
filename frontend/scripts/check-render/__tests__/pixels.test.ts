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
 * THE PROBE'S FIDELITY TO THE COMPONENTS IT STANDS IN FOR is asserted beside them, in
 * `src/ui/domain/week-grid/__tests__/probe.test.tsx`, because it is a claim about what `Block` and the grid render and
 * it needs JSX, which the script suite's own file pattern does not take. */

import { describe, expect, it } from "vitest";

import { CASES, geometryOf, heightOf, linesOf, tierOf } from "../page.ts";
import { pxPerMinute } from "../../../src/ui/domain/week-grid/geometry.ts";
import { tierFor, titleLineCount } from "../../../src/ui/domain/week-grid/tiers.ts";
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
  /* THE PROBE'S ARITHMETIC AGAINST THE DOMAIN'S, SWEPT RATHER THAN SAMPLED, AND IN BOTH DIRECTIONS.
   *
   * `page.ts` restates three formulas because it cannot import them: `tiers.ts` and `geometry.ts` import `./metrics`
   * without an extension, which a bundler resolves and the runtime a script runs under does not. So this file, which
   * runs under the bundler, imports both sides and requires them to agree at every height rather than at the six the
   * gate happens to ship. Literals here pinned only the probe: a structural change to the ladder would redden the
   * ladder's own test, the author would update that, and the probe would keep measuring a line count the product never
   * sets. That sweep is what makes a divergence fail on whichever side moves. */
  it("agrees with the ladder and the tier at every quarter-pixel from 0 to 220", () => {
    for (let heightPx = 0; heightPx <= 220; heightPx += 0.25) {
      expect(linesOf(heightPx), `lines at ${String(heightPx)}px`).toBe(titleLineCount(heightPx));
      expect(tierOf(heightPx), `tier at ${String(heightPx)}px`).toBe(tierFor(heightPx));
    }
  });

  it("agrees with pixels per minute at every zoom the range offers", () => {
    for (let visibleHours = 6; visibleHours <= 24; visibleHours += 1) {
      for (const durationMinutes of [15, 30, 60, 90, 240]) {
        expect(heightOf(durationMinutes, visibleHours)).toBeCloseTo(
          durationMinutes * pxPerMinute(0, visibleHours),
          10,
        );
      }
    }
  });

  /* THE LADDER IS THE DOMAIN'S, so this asserts that the geometry AGREES with it rather than restating the numbers.
   * The literals were the only thing pinning the probe, and they pinned it in one direction: a structural change to
   * `titleLineCount` would redden its own test, the author would update that, and the probe would keep measuring a
   * line count the product never sets. */
  it("takes each height from the reference display and each line count from the ladder itself", () => {
    expect(heightOf(30, 12)).toBeCloseTo(26.083, 3);

    for (const each of geometryOf(CASES)) {
      expect(each.lines).toBe(titleLineCount(each.heightPx));
    }
  });

  it("reaches past eight lines, which is where the reader used to walk out of its own region", () => {
    const deepest = geometryOf(CASES).reduce((most, each) => Math.max(most, each.lines), 0);

    expect(deepest).toBeGreaterThan(8);
  });

  it("renders each case twice, capped and uncapped, at its own place on the page", () => {
    const cases = geometryOf(CASES);

    for (const each of cases) expect(each.uncappedTopPx).toBeGreaterThan(each.cappedTopPx);
    expect(new Set(cases.map((each) => each.cappedTopPx)).size).toBe(cases.length);
  });
});
