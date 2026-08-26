/* THE QUARTER LINES' WEIGHT, BEFORE AND DURING A DRAG, AS THE BROWSER COMPOSED IT.
 *
 * `grid.css` re-weights the quarter lines while `[data-dragging]` sits on the grid, and every assertion about that
 * until now read the DECLARATION. What the reader sees is the cascade's outcome: the computed `border-top-color` a
 * quarter line carries at rest, and the one it carries once the attribute lands on the grid ancestor. One canvas
 * with both kinds of line is enough to measure that, because the re-weighting keys on the grid rather than on each
 * line and every column draws the same lines.
 *
 * THE SECTION SHIPS AT REST and the reading script puts the attribute on itself, reading both states in one pass.
 * A second copy parked permanently mid-drag would measure nothing the flip does not, and would double the page for
 * it. Computed style answers synchronously after a mutation, so the two readings are two moments of one document.
 *
 * WHAT HOLDS THIS TO THE PRODUCT is `src/ui/domain/week-grid/__tests__/probe.test.tsx`: it renders the real
 * `WeekGrid` over the same slice of the axis and requires this markup to draw the same lines with the same classes,
 * the way it holds the block and the seven day columns. */

import {
  GRID_H_PX,
  GRID_MAJOR_MINUTES,
  GRID_MINOR_MINUTES,
  VISIBLE_HOURS_DEFAULT,
} from "../../src/ui/domain/week-grid/metrics.ts";

/** Where the page reports the two weighings, one channel of its own. */
export const LINE_READINGS_ID = "line-readings";

/** Three hours of the axis, so hour lines and quarter lines both exist to be compared. */
export const LINE_EXTENT = { startMin: 360, endMin: 480 } as const;

/** The pixels-per-minute figure `WEEK_SECTION` draws at, restated to avoid an import cycle through `page.ts`. */
const PX_PER_MIN = GRID_H_PX / (VISIBLE_HOURS_DEFAULT * 60);

const CONTAINER_ID = "lines";
const PLACES = 3;

/** What one weighing reported: the composed ink of each kind of line. */
export interface LineWeights {
  readonly hour: string;
  readonly quarter: string;
}

export interface LineWeightReading {
  readonly atRest: LineWeights;
  readonly dragging: LineWeights;
  /** Present only where the page could measure nothing at all, which is a fault in the instrument. */
  readonly error?: string | undefined;
}

export interface LineWeightSection {
  readonly html: string;
  readonly script: string;
  readonly heightPx: number;
}

/** The minute offsets `lineOffsets` computes for this slice, hours and quarters alike, lowest first. */
export function sectionLineOffsets(): number[] {
  const first = Math.ceil(LINE_EXTENT.startMin / GRID_MINOR_MINUTES) * GRID_MINOR_MINUTES;
  const offsets: number[] = [];
  for (let minute = first; minute <= LINE_EXTENT.endMin; minute += GRID_MINOR_MINUTES) {
    offsets.push(minute);
  }
  return offsets;
}

/** One canvas of day column, carrying the lines `GridLines` draws, in the classes it draws them with. */
export function lineWeightSection(): LineWeightSection {
  const canvasHeightPx = (LINE_EXTENT.endMin - LINE_EXTENT.startMin) * PX_PER_MIN;
  const lines = sectionLineOffsets()
    .map((minute) => {
      const kind = minute % GRID_MAJOR_MINUTES === 0 ? "hour" : "quarter";
      return (
        `<div aria-hidden="true" class="week-grid__line week-grid__line--${kind}" ` +
        `style="top:${((minute - LINE_EXTENT.startMin) * PX_PER_MIN).toFixed(PLACES)}px"></div>`
      );
    })
    .join("");

  return {
    html:
      `<div id="${CONTAINER_ID}">` +
      `<div class="week-grid max-narrow:overflow-x-auto">` +
      `<div class="week-grid__days">` +
      `<div class="week-day max-narrow:shrink-0 max-narrow:grow-0 max-narrow:basis-col-min">` +
      `<div class="week-day__canvas" style="height:${canvasHeightPx.toFixed(PLACES)}px">${lines}</div>` +
      `</div></div></div></div>`,
    script: readingScript(),
    heightPx: Math.ceil(canvasHeightPx),
  };
}

function readingScript(): string {
  return `
  (() => {
    const report = (value) => {
      document.getElementById(${JSON.stringify(LINE_READINGS_ID)}).textContent = JSON.stringify(value);
    };
    const grid = document.querySelector("#${CONTAINER_ID} .week-grid");
    const hour = document.querySelector("#${CONTAINER_ID} .week-grid__line--hour");
    const quarter = document.querySelector("#${CONTAINER_ID} .week-grid__line--quarter");
    if (grid === null || hour === null || quarter === null) {
      report({ error: "the page rendered no line-weight section, so the drag's re-weighting was never measured" });
      return;
    }
    const weightOf = (line) => getComputedStyle(line).borderTopColor;
    const atRest = { hour: weightOf(hour), quarter: weightOf(quarter) };
    grid.setAttribute("data-dragging", "");
    const dragging = { hour: weightOf(hour), quarter: weightOf(quarter) };
    grid.removeAttribute("data-dragging");
    report({ atRest, dragging });
  })();
`;
}
