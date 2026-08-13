/* WHAT THE GRID REPORTS UPWARD, AND WHY THE MEASUREMENT'S LOCATION IS WHAT MAKES IT WORTH ANYTHING.
 *
 * The clamp runs inside this component because only this component has a measurement, and that leaves the surfaces
 * above it with no way to know which level was drawn. The report is that way back. These cases hold it against the
 * rendering it claims to describe: every one of them reads the reported figure AND the canvas height the same render
 * produced, because a report asserted alone would describe a call rather than a drawing.
 *
 * THE HEIGHT IS STUBBED ON `Element.prototype`, as `grid.test.tsx` stubs it, because the hook reads it through the ref
 * it observes and there is no instance to reach before the effect runs. jsdom lays nothing out, so without the stub
 * every case here would measure the reference display and the two rows below would be the same row.
 *
 * A CHANGE OF MEASUREMENT IS NOT DRIVEN HERE. jsdom's `ResizeObserver` never calls back, so a resize is a browser's
 * business; what is driven is the other half of the same keying, a level changed at one height. */

import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { WeekGrid } from "../WeekGrid";
import { DAY_HEADER_H_PX, ZOOM_MAX_HOURS, ZOOM_MIN_HOURS } from "../metrics";
import type { Extent, WeekDay, ZoomReport } from "..";

const DATE = "2026-02-09";
const EXTENT: Extent = { startMin: 300, endMin: 1440 };
const EXTENT_MINUTES = EXTENT.endMin - EXTENT.startMin;

/** The grid a 13 inch reference display yields, whose cap is 16. */
const REFERENCE_GRID_PX = 626;

/** A grid tall enough for the whole range, which is the display the clamp must not cap at the reference's 16. */
const TALL_GRID_PX = 950;

const DAY: WeekDay = {
  date: DATE,
  zone: "Europe/London",
  startMs: Date.parse(`${DATE}T00:00:00Z`),
  minutes: 1440,
  blocks: [],
  bands: [],
};

/** The canvas height a column takes at a zoom, from the two figures the geometry is derived from and nothing else. */
function canvasHeightAt(gridPx: number, hours: number): string {
  return `${(EXTENT_MINUTES * (gridPx / (hours * 60))).toFixed(3)}px`;
}

/** The deepest level the reported range offers, which is the display's own cap as the report states it. */
function deepestOffered(report: ZoomReport): number | undefined {
  return report.levels.findLast((level) => level.isAvailable)?.hours;
}
describe("the level and the range the grid reports", () => {
  let measuredGridPx = REFERENCE_GRID_PX;
  let original: PropertyDescriptor | undefined;
  const reports: ZoomReport[] = [];
  const onZoom = (report: ZoomReport): void => {
    reports.push(report);
  };

  /** The last report, or a failure that names the silence rather than an assertion against `undefined`. */
  const lastReport = (): ZoomReport => {
    const report = reports.at(-1);
    if (report === undefined) throw new Error("the grid reported nothing");
    return report;
  };

  beforeEach(() => {
    measuredGridPx = REFERENCE_GRID_PX;
    reports.length = 0;
    original = Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight");
    Object.defineProperty(Element.prototype, "clientHeight", {
      configurable: true,
      get() {
        return measuredGridPx + DAY_HEADER_H_PX;
      },
    });
  });

  afterEach(() => {
    if (original === undefined)
      delete (Element.prototype as { clientHeight?: unknown }).clientHeight;
    else Object.defineProperty(Element.prototype, "clientHeight", original);
  });

  function renderGrid(visibleHours: number) {
    const view = render(
      <WeekGrid
        days={[DAY]}
        extent={EXTENT}
        labels={[DATE]}
        nowMs={null}
        onZoom={onZoom}
        visibleHours={visibleHours}
      />,
    );
    const canvasHeight = (): string =>
      (view.container.querySelector(".week-day__canvas") as HTMLElement).style.height;
    const draw = (hours: number) => {
      view.rerender(
        <WeekGrid
          days={[DAY]}
          extent={EXTENT}
          labels={[DATE]}
          nowMs={null}
          onZoom={onZoom}
          visibleHours={hours}
        />,
      );
    };
    return { canvasHeight, draw };
  }

  it("reports the level it drew, which on this display is not the level it was given", () => {
    const proposed = 20;
    const { canvasHeight } = renderGrid(proposed);

    expect(lastReport().hours).toBe(16);
    expect(canvasHeight()).toBe(canvasHeightAt(REFERENCE_GRID_PX, 16));
    expect(canvasHeight()).not.toBe(canvasHeightAt(REFERENCE_GRID_PX, proposed));
  });

  it("reports the whole range, each level marked with whether this display can offer it", () => {
    renderGrid(20);
    const report = lastReport();

    expect(report.levels.map((level) => level.hours)).toEqual(
      Array.from({ length: ZOOM_MAX_HOURS - ZOOM_MIN_HOURS + 1 }, (_, i) => ZOOM_MIN_HOURS + i),
    );
    expect(deepestOffered(report)).toBe(16);
    for (const level of report.levels.filter((each) => !each.isAvailable))
      expect(level.unavailableReason).not.toBeNull();
  });

  /* THE REGRESSION THE MEASUREMENT'S LOCATION PROTECTS. Clamping above this component would answer from the reference
   * display's 626px, and a reader who paid for a taller display would be reported and drawn at 16 with a third of the
   * range taken away. Both figures are read here, because a report of 24 over a grid drawing 16 is the same defect the
   * report exists to close, one direction over. */
  it("keeps a taller display's own deeper level, in the report and in the drawing", () => {
    measuredGridPx = TALL_GRID_PX;
    const { canvasHeight } = renderGrid(24);

    expect(lastReport().hours).toBe(24);
    expect(deepestOffered(lastReport())).toBe(24);
    expect(canvasHeight()).toBe(canvasHeightAt(TALL_GRID_PX, 24));
    expect(canvasHeight()).not.toBe(canvasHeightAt(TALL_GRID_PX, 16));
  });

  it("reports once per measurement rather than once per render", () => {
    const { draw } = renderGrid(12);

    draw(12);

    expect(reports).toHaveLength(1);
  });

  it("reports again where the level changes, so a cycled level reaches whatever states it", () => {
    const { canvasHeight, draw } = renderGrid(12);

    draw(6);

    expect(reports.map((report) => report.hours)).toEqual([12, 6]);
    expect(canvasHeight()).toBe(canvasHeightAt(REFERENCE_GRID_PX, 6));
  });
});
