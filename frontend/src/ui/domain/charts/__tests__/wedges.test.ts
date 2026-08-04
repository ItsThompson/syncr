/* THE PIE'S ARITHMETIC AT ITS BOUNDARIES: no category, one category, a category holding zero, one holding a
 * negative, and thirteen where a pigment repeats.
 *
 * These are asserted here rather than through a rendering because a wedge's honesty is arithmetic: whether the
 * shares are taken against what was actually drawn, whether the last arc closes on the first one's start, and
 * whether a label sits outside the circle. A DOM test can then check the component draws what this returns. */

import { describe, expect, it } from "vitest";

import { PIE, layOutPie } from "../wedges";
import { UNALLOCATED, type AreaQuantity } from "../series";
import { AREA_PIGMENTS } from "../../marks/pigment";

/**
 * The smallest gap two labels may sit at, as a literal.
 *
 * NOT `PIE.labelPitch`. Reading the constant the implementation spaces by makes the assertion self-referential:
 * setting that constant to 0 disables the whole spread and a test that derives its expectation from it goes on
 * passing, which is exactly what a reviewer measured. 12 is the figure the constant's own doc states its reason
 * against, a glyph box at --fs-eyebrow being a little under 12px tall, so the two agree without sharing a source.
 */
const MIN_GAP = 12;

function slice(id: string, minutes: number, overrides: Partial<AreaQuantity> = {}): AreaQuantity {
  return { id, label: id, pigment: "01", minutes, ...overrides };
}

/** The two coordinates a wedge's arc ends on, which is where the next wedge starts. */
function endOf(d: string): string {
  const arc = /A[\d.]+ [\d.]+ 0 [01] 1 ([\d.]+) ([\d.]+)Z$/.exec(d);
  if (arc === null) throw new Error(`no closing arc in ${d}`);
  return `${arc[1]} ${arc[2]}`;
}

function startOf(d: string): string {
  const line = / L([\d.]+) ([\d.]+)/.exec(d);
  if (line === null) throw new Error(`no radius in ${d}`);
  return `${line[1]} ${line[2]}`;
}

describe("a composition with nothing in it", () => {
  it("draws no wedge at all", () => {
    expect(layOutPie([]).wedges).toEqual([]);
  });

  it("takes its total from what could be drawn, so an empty pie divides by nothing", () => {
    expect(layOutPie([]).total).toBe(0);
    expect(layOutPie([slice("career", 0), slice("study", 0)]).total).toBe(0);
  });

  it("still states the box, so a caller's layout does not move when a period fills up", () => {
    const empty = layOutPie([]);
    const filled = layOutPie([slice("career", 60)]);

    expect(empty.width).toBe(filled.width);
    expect(empty.height).toBe(filled.height);
  });
});

describe("a composition with one category in it", () => {
  const single = layOutPie([slice("career", 820)]);

  /* THE DEGENERATE ARC EVERY PIE MEETS. A single category owns the full turn, and an arc whose start and end are
   * the same point draws nothing, so the whole circle is drawn as two half arcs instead. */
  it("draws a whole circle rather than an arc that closes on itself", () => {
    expect(single.wedges).toHaveLength(1);
    expect(single.wedges[0].d.match(/A/g)).toHaveLength(2);
    expect(single.wedges[0].d).not.toContain("L");
  });

  it("gives it the whole share", () => {
    expect(single.wedges[0].share).toBe(1);
    expect(single.total).toBe(820);
  });

  it("labels it, because a wedge with no label is a colour and nothing else", () => {
    expect(single.wedges[0].label).toBe("career");
  });
});

describe("a category holding nothing", () => {
  it("draws no wedge and leaves the shares to the ones that could be drawn", () => {
    const laid = layOutPie([slice("career", 60), slice("study", 0), slice("admin", 60)]);

    expect(laid.wedges.map((wedge) => wedge.id)).toEqual(["career", "admin"]);
    expect(laid.wedges.map((wedge) => wedge.share)).toEqual([0.5, 0.5]);
  });

  /* A NEGATIVE TAKES THE SAME PATH AS A ZERO. Oversubscription is reported as its own quantity and never as a
   * negative category, so a negative minute count is a caller's arithmetic error: what it must not do is invert
   * an arc or make the total smaller than a part. */
  it("takes the same path as one holding a negative, which nothing in the product can produce", () => {
    const laid = layOutPie([slice("career", 60), slice("over", -30)]);

    expect(laid.wedges.map((wedge) => wedge.id)).toEqual(["career"]);
    expect(laid.total).toBe(60);
  });
});

describe("a full composition", () => {
  const laid = layOutPie([
    slice("career", 300, { pigment: "01" }),
    slice("study", 180, { pigment: "05" }),
    slice("unallocated", 120, { pigment: UNALLOCATED, label: "Unallocated" }),
  ]);

  it("takes every share against the same total, so the wedges cannot disagree with the ledger", () => {
    expect(laid.total).toBe(600);
    expect(laid.wedges.map((wedge) => wedge.share)).toEqual([0.5, 0.3, 0.2]);
    expect(laid.wedges.reduce((sum, wedge) => sum + wedge.share, 0)).toBe(1);
  });

  it("starts each wedge where the last one ended", () => {
    expect(startOf(laid.wedges[1].d)).toBe(endOf(laid.wedges[0].d));
    expect(startOf(laid.wedges[2].d)).toBe(endOf(laid.wedges[1].d));
  });

  /* The last arc has to land back on the first wedge's own radius. A pie assembled from independently rounded
   * angles leaves a sliver of paper between the last wedge and the first, which reads as a thirteenth category. */
  it("closes the circle exactly, so no sliver of paper is left between the last wedge and the first", () => {
    expect(endOf(laid.wedges[2].d)).toBe(startOf(laid.wedges[0].d));
  });

  it("starts at twelve o'clock and runs clockwise", () => {
    const [x, y] = startOf(laid.wedges[0].d).split(" ").map(Number);

    expect(x).toBe(laid.width / 2);
    expect(y).toBe(laid.height / 2 - PIE.radius);
    // The first wedge covers half the circle, so it ends at six o'clock.
    const [endX, endY] = endOf(laid.wedges[0].d).split(" ").map(Number);

    expect(endX).toBe(laid.width / 2);
    expect(endY).toBe(laid.height / 2 + PIE.radius);
  });

  it("marks the major arc only where a wedge is more than half the circle", () => {
    const half = layOutPie([slice("most", 300), slice("rest", 60)]);

    expect(half.wedges[0].d).toContain(`A${PIE.radius} ${PIE.radius} 0 1 1`);
    expect(half.wedges[1].d).toContain(`A${PIE.radius} ${PIE.radius} 0 0 1`);
  });
});

describe("where a wedge's label sits", () => {
  const laid = layOutPie([slice("right", 300), slice("left", 300)]);

  /* LABELS SIT OUTSIDE THE WEDGES. A wedge fill only has to clear 3:1 as an indicator; text on a fill would need
   * 4.5:1, so a label is never drawn on one. The x is fixed per side, one column each, so a label cannot reach the
   * circle however crowded its column becomes. */
  it("sits clear of the circle, in a column on its own side", () => {
    for (const wedge of laid.wedges) {
      expect(Math.abs(wedge.labelAt.x - laid.width / 2)).toBe(PIE.radius + PIE.labelGap);
    }
  });

  it("reads away from the arc: from the anchor outward on each side", () => {
    expect(laid.wedges[0].labelAt.anchor).toBe("start");
    expect(laid.wedges[1].labelAt.anchor).toBe("end");
  });

  it("tracks its own wedge's height where there is room for it", () => {
    const quarters = layOutPie([slice("top", 1), slice("bottom", 1)]);

    expect(quarters.wedges[0].labelAt.y).toBe(quarters.height / 2);
    expect(quarters.wedges[1].labelAt.y).toBe(quarters.height / 2);
  });

  /* FOUR THIN WEDGES BESIDE EACH OTHER IS NOT A HYPOTHETICAL. The rendered composition puts `Transit`,
   * `Projects`, `Research` and `Admin` inside 6% of the circle, and their labels landed on top of each other in a
   * browser before this spread existed. */
  it("is pushed clear of its neighbour when a column crowds", () => {
    const crowded = layOutPie([
      slice("huge", 940),
      slice("thin-a", 15),
      slice("thin-b", 15),
      slice("thin-c", 15),
      slice("thin-d", 15),
    ]);

    for (const anchor of ["start", "end"] as const) {
      const column = crowded.wedges
        .filter((wedge) => wedge.labelAt.anchor === anchor)
        .map((wedge) => wedge.labelAt.y)
        .toSorted((one, two) => one - two);
      for (let index = 1; index < column.length; index += 1) {
        expect(column[index] - column[index - 1]).toBeGreaterThanOrEqual(MIN_GAP);
      }
    }
  });

  /* The pitch itself, pinned to the same literal. Without this the assertion above and the implementation share
   * one oracle: `PIE.labelPitch: 0` turns the spread off and leaves every gap legal. */
  it("is spaced by a pitch that clears a glyph box, which is what the spread is for", () => {
    expect(PIE.labelPitch).toBeGreaterThanOrEqual(MIN_GAP);
  });

  it("stays inside the box the gutter reserves for it, even at thirteen", () => {
    const thirteen = layOutPie(
      AREA_PIGMENTS.map((pigment, index) =>
        slice(`area-${pigment}`, index === 0 ? 900 : 4, { pigment }),
      ).concat(slice("thirteenth", 4)),
    );

    for (const wedge of thirteen.wedges) {
      expect(wedge.labelAt.x).toBeGreaterThan(0);
      expect(wedge.labelAt.x).toBeLessThan(thirteen.width);
      expect(wedge.labelAt.y).toBeGreaterThan(0);
      expect(wedge.labelAt.y).toBeLessThan(thirteen.height);
    }
  });
});

describe("a thirteenth category", () => {
  const thirteen = [
    ...AREA_PIGMENTS.map((pigment, index) =>
      slice(`area-${pigment}`, 60 + index, { pigment, label: `Area ${pigment}` }),
    ),
    slice("area-13", 200, { pigment: AREA_PIGMENTS[0], label: "Thirteenth" }),
  ];
  const laid = layOutPie(thirteen);

  it("is drawn, because the ramp repeating is not a reason to hide an Area", () => {
    expect(laid.wedges).toHaveLength(13);
  });

  it("repeats a pigment, which is what makes the label the identity", () => {
    const pigments = laid.wedges.map((wedge) => wedge.pigment);
    const labels = laid.wedges.map((wedge) => wedge.label);

    expect(new Set(pigments).size).toBe(12);
    expect(new Set(labels).size).toBe(13);
  });

  it("closes the circle across all thirteen", () => {
    expect(endOf(laid.wedges[12].d)).toBe(startOf(laid.wedges[0].d));
  });
});
