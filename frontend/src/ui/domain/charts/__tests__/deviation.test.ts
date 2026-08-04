/* THE SIGNED DEVIATION'S ARITHMETIC: an empty set, one row, a row exactly on target, and a set where every row
 * is on target.
 *
 * The scale is the part worth asserting. It is symmetric about zero and taken from the largest absolute
 * deviation in the set, so no bar is clipped and the axis states the same figure the bars were sized by. The
 * rendered screens draw this chart against a FIXED twelve-point span and clamp at half the track, which clips
 * whichever row went furthest off target: that is the row the chart exists to show, so it is not clipped here. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { srcDir } from "../../../../testing/compileTheme";
import { kitStylesheet } from "../../../../testing/kitStylesheets";
import { MINUS_SIGN, plotDeviations } from "../deviation";
import type { DeviationRow } from "../series";

function row(id: string, actual: number, target: number): DeviationRow {
  return { id, label: id, actual, target };
}

describe("the sign", () => {
  /* U+2212 MINUS SIGN, and the kit's glyph table is where that choice is written. A hyphen sets narrower than a
   * plus, so a column of signed figures would not align, and the two are indistinguishable in a literal. */
  it("is the same codepoint the kit's glyph table declares", async () => {
    const table = await kitStylesheet("glyphs.css");
    const declared = /--glyph-minus:\s*"\\([0-9A-F]+)"/.exec(table);

    expect(declared).not.toBeNull();
    expect(MINUS_SIGN).toBe(String.fromCodePoint(Number.parseInt(declared?.[1] ?? "", 16)));
  });

  it("is not a hyphen", () => {
    expect(MINUS_SIGN).not.toBe("-");
  });

  it("carries direction, so a bar's side is restated in words a screen reader reaches", () => {
    const { plotted } = plotDeviations([row("under", 3, 8), row("over", 9, 8), row("on", 8, 8)]);

    expect(plotted.map((entry) => entry.sign)).toEqual([MINUS_SIGN, "+", ""]);
  });
});

describe("direction", () => {
  it("is side and sign, and the two sides are the same ink", () => {
    const { plotted } = plotDeviations([row("under", 3, 8), row("over", 9, 8)]);

    expect(plotted.map((entry) => entry.side)).toEqual(["under", "over"]);
  });

  it("is `on` at exactly the target, which draws no bar at all", () => {
    const { plotted } = plotDeviations([row("exact", 8, 8)]);

    expect(plotted[0].side).toBe("on");
    expect(plotted[0].deviation).toBe(0);
  });
});

describe("the scale", () => {
  it("is the largest absolute deviation in the set, whichever direction it points", () => {
    expect(plotDeviations([row("a", 3, 8), row("b", 9, 8)]).scale).toBe(5);
    expect(plotDeviations([row("a", 7, 8), row("b", 20, 8)]).scale).toBe(12);
  });

  it("gives the largest row half the track, so no bar is ever clipped", () => {
    const { plotted } = plotDeviations([row("worst", 0, 10), row("small", 9, 10)]);

    expect(plotted[0].width).toBe(50);
    expect(plotted[1].width).toBe(5);
  });

  /* EVERY ROW ON TARGET LEAVES NOTHING TO SCALE AGAINST. A division by zero here would put NaN into a width and
   * render a bar of no length beside an axis reading NaN. */
  it("is zero when every row is exactly on target, and no bar takes a width", () => {
    const { plotted, scale } = plotDeviations([row("a", 8, 8), row("b", 5, 5)]);

    expect(scale).toBe(0);
    expect(plotted.map((entry) => entry.width)).toEqual([0, 0]);
  });

  it("is zero for an empty set, which draws no row and no axis", () => {
    expect(plotDeviations([])).toEqual({ plotted: [], scale: 0 });
  });

  it("comes from one row alone when that is all there is", () => {
    const { plotted, scale } = plotDeviations([row("only", 2, 8)]);

    expect(scale).toBe(6);
    expect(plotted[0].width).toBe(50);
    expect(plotted[0].side).toBe("under");
  });
});

describe("a row", () => {
  it("keeps its own figures, so the chart never restates them", () => {
    const { plotted } = plotDeviations([row("career", 27.3, 30)]);

    expect(plotted[0].row.actual).toBe(27.3);
    expect(plotted[0].row.target).toBe(30);
    expect(plotted[0].deviation).toBeCloseTo(-2.7, 10);
  });

  /* A CHART ROW IS A CHART CONTEXT END TO END, so a row carries no Area pigment anywhere, including its label
   * cell. The type is what refuses one, which is why this reads the type rather than a rendering. */
  it("has no pigment field for an Area ink to arrive through", async () => {
    const source = await readFile(path.join(srcDir, "ui", "domain", "charts", "series.ts"), "utf8");
    const declaration = /export interface DeviationRow \{([^}]*)\}/.exec(source);

    expect(declaration).not.toBeNull();
    expect(declaration?.[1]).not.toContain("pigment");
  });
});
