/* THE AXIS NEVER LIES, ASSERTED AT THE EDGES RATHER THAN IN THE MIDDLE.
 *
 * Every claim here is one of the two rules the geometry exists to keep: the axis expands to contain every span, and
 * height is proportional to duration at every zoom level. The cases are the boundaries the ticket names, because a
 * proportional axis is easy to get right for a one-hour block at noon and is where an hour goes missing for a
 * zero-length one, an abutting pair, a span across midnight, and a day that is 23 or 25 hours long. */

import { describe, expect, it } from "vitest";

import {
  boxOf,
  canvasHeightPx,
  extentOf,
  lineOffsets,
  offsetSpanOf,
  pxPerMinute,
  totalMinutes,
} from "../geometry";
import { GRID_H_PX, VISIBLE_HOURS_DEFAULT } from "../metrics";

const at = (iso: string): number => Date.parse(iso);
const MINUTES_IN_DAY = 1440;

describe("total minutes", () => {
  it("comes from the two instants, so an ordinary day is 1440", () => {
    const day = { startMs: at("2026-02-09T00:00:00Z"), endMs: at("2026-02-10T00:00:00Z") };

    expect(totalMinutes(day)).toBe(MINUTES_IN_DAY);
  });

  it("is 1380 across a spring-forward transition, which no assumed 1440 could produce", () => {
    const day = { startMs: at("2026-03-29T00:00:00Z"), endMs: at("2026-03-29T23:00:00Z") };

    expect(totalMinutes(day)).toBe(23 * 60);
  });

  it("is 1500 across a fall-back transition", () => {
    const day = { startMs: at("2026-10-24T23:00:00Z"), endMs: at("2026-10-26T00:00:00Z") };

    expect(totalMinutes(day)).toBe(25 * 60);
  });

  it("is zero for a zero-length span rather than absent", () => {
    const instant = at("2026-02-09T09:00:00Z");

    expect(totalMinutes({ startMs: instant, endMs: instant })).toBe(0);
  });
});

describe("a span's offset inside a column", () => {
  const columnStartMs = at("2026-02-09T00:00:00Z");

  it("is minutes from the column's own start", () => {
    const span = { startMs: at("2026-02-09T09:30:00Z"), endMs: at("2026-02-09T10:00:00Z") };

    expect(offsetSpanOf(span, columnStartMs)).toEqual({ startMin: 570, endMin: 600 });
  });

  it("is NEGATIVE for a span that began before the column, which is the overhang", () => {
    const span = { startMs: at("2026-02-08T23:00:00Z"), endMs: at("2026-02-09T07:00:00Z") };

    expect(offsetSpanOf(span, columnStartMs)).toEqual({ startMin: -60, endMin: 420 });
  });

  it("runs past a day for a span that ends after the column, which is the Sunday-night tail", () => {
    const span = { startMs: at("2026-02-09T23:00:00Z"), endMs: at("2026-02-10T07:00:00Z") };

    expect(offsetSpanOf(span, columnStartMs)).toEqual({ startMin: 1380, endMin: 1860 });
  });
});

describe("the extent", () => {
  const bounds = { startMin: 360, endMin: 1320 };

  it("is the declared bounds when nothing lies outside them", () => {
    const inside = [{ startMin: 540, endMin: 600 }];

    expect(extentOf(bounds, inside)).toEqual(bounds);
  });

  it("EXPANDS to contain a span the bounds would have cropped, in both directions", () => {
    const outside = [
      { startMin: 0, endMin: 315 },
      { startMin: 1380, endMin: 1860 },
    ];

    expect(extentOf(bounds, outside)).toEqual({ startMin: 0, endMin: 1860 });
  });

  it("contains a span that started before the column, rather than clamping it to zero", () => {
    expect(extentOf(bounds, [{ startMin: -60, endMin: 420 }])).toEqual({
      startMin: -60,
      endMin: 1320,
    });
  });

  it("clips NO span: every one given is inside the result", () => {
    const spans = [
      { startMin: -60, endMin: 420 },
      { startMin: 0, endMin: 0 },
      { startMin: 720, endMin: 720 },
      { startMin: 1380, endMin: 1860 },
    ];
    const extent = extentOf(bounds, spans);

    for (const span of spans) {
      expect(span.startMin).toBeGreaterThanOrEqual(extent.startMin);
      expect(span.endMin).toBeLessThanOrEqual(extent.endMin);
    }
  });
});

describe("pixels per minute", () => {
  it("is the measured height over the visible minutes, which is the whole derivation", () => {
    expect(pxPerMinute(626, 12)).toBeCloseTo(626 / 720, 10);
  });

  it("stands in the reference display's height while nothing has been measured", () => {
    expect(pxPerMinute(0, VISIBLE_HOURS_DEFAULT)).toBe(GRID_H_PX / (VISIBLE_HOURS_DEFAULT * 60));
  });

  it("keeps height proportional to duration at every zoom level", () => {
    for (const hours of [6, 12, 16, 22, 24]) {
      const pxPerMin = pxPerMinute(626, hours);
      const fifteen = boxOf({ startMin: 0, endMin: 15 }, { startMin: 0, endMin: 1440 }, pxPerMin);
      const thirty = boxOf({ startMin: 0, endMin: 30 }, { startMin: 0, endMin: 1440 }, pxPerMin);

      expect(thirty.heightPx).toBeCloseTo(fifteen.heightPx * 2, 10);
    }
  });
});

describe("a span's box", () => {
  const extent = { startMin: 300, endMin: 1440 };
  const pxPerMin = 0.5;

  it("is measured from the extent's start rather than from midnight", () => {
    expect(boxOf({ startMin: 360, endMin: 420 }, extent, pxPerMin)).toEqual({
      topPx: 30,
      heightPx: 30,
    });
  });

  it("is zero-height for a zero-length span, which is drawn rather than dropped", () => {
    expect(boxOf({ startMin: 600, endMin: 600 }, extent, pxPerMin)).toEqual({
      topPx: 150,
      heightPx: 0,
    });
  });

  it("puts two abutting spans edge to edge with no gap and no overlap", () => {
    const first = boxOf({ startMin: 540, endMin: 600 }, extent, pxPerMin);
    const second = boxOf({ startMin: 600, endMin: 660 }, extent, pxPerMin);

    expect(first.topPx + first.heightPx).toBe(second.topPx);
  });

  it("has NO floor on a height, because the block degrades and the axis does not", () => {
    const sliver = boxOf({ startMin: 540, endMin: 541 }, extent, 0.1);

    expect(sliver.heightPx).toBeCloseTo(0.1, 10);
  });
});

describe("the canvas", () => {
  it("is the whole extent tall, not the visible window, so the axis holds what it contains", () => {
    const extent = { startMin: 0, endMin: 1860 };
    const pxPerMin = pxPerMinute(626, 12);

    expect(canvasHeightPx(extent, pxPerMin)).toBeCloseTo(1860 * pxPerMin, 10);
    expect(canvasHeightPx(extent, pxPerMin)).toBeGreaterThan(626);
  });

  it("is zero for an extent of no width, rather than negative", () => {
    expect(canvasHeightPx({ startMin: 600, endMin: 600 }, 0.87)).toBe(0);
  });
});

describe("the grid lines", () => {
  it("start at the first mark inside the extent, not at the extent's own edge", () => {
    expect(lineOffsets({ startMin: 315, endMin: 480 }, 60)).toEqual([360, 420, 480]);
  });

  it("draw a quarter mark between every pair of hour marks", () => {
    const quarters = lineOffsets({ startMin: 0, endMin: 60 }, 15);

    expect(quarters).toEqual([0, 15, 30, 45, 60]);
  });

  it("reach the extent's end, so the last hour of the week is drawn", () => {
    const hours = lineOffsets({ startMin: 1380, endMin: 1860 }, 60);

    expect(hours.at(-1)).toBe(1860);
  });

  it("is empty rather than infinite for a spacing of zero", () => {
    expect(lineOffsets({ startMin: 0, endMin: 60 }, 0)).toEqual([]);
  });
});
