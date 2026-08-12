/* SEVEN REAL DAY COLUMNS, AND WHAT A POINTER OVER ONE OF THEM NAMES IN THE COLUMN BESIDE IT.
 *
 * WHY THIS IS IN A BROWSER RATHER THAN IN A TEST. The drag reads a pointer position against the box of the column it
 * pressed in, on both axes, and a release outside that box states no placement. jsdom lays nothing out, so every test
 * that exercises the drag stubs `getBoundingClientRect`, and it stubs it to ONE box for every canvas. A position "over
 * the next column" is then a position the test invented: nothing in that DOM says where the next column is. Seven
 * columns laid out by the built stylesheet is the only place this repository can ask the question at all.
 *
 * THE READ IS THE PRODUCT'S OWN, compiled into the page from `useDiscreteDrag.ts` rather than restated here. A
 * restatement would stay green with the horizontal comparison deleted from the module that ships, which is the one
 * defect these readings exist to catch.
 *
 * WHAT IS MEASURED IS THE READ, NOT A RELEASE, and the reason is the size of the instrument rather than a refusal from
 * the platform. A page may dispatch a `pointerdown` and capture the mouse's own pointer id without either being
 * trusted; only an id no pointer holds is refused, with `NotFoundError`. The whole horizontal decision is inside
 * `pointAt`, so a position over the next column and the box it is read against is the entire question, and pressing
 * for real would add a React runtime, a fixture in generated code and a mount to wait for to answer the same
 * comparison. One thing a dispatched sequence cannot reach either way: it emits no `gotpointercapture` and no
 * `lostpointercapture` at all, so the drag's cancel-on-capture-loss is not observable from a page that presses itself.
 *
 * THE COLUMNS CARRY NO BLOCKS, NO BANDS AND NO GRID LINES. All of those are absolutely positioned, so none can move
 * the box a read is taken against, and the nine title cases already stand in for a block. What remains is the column
 * frame, which is exactly what `DayColumn` renders for a day holding nothing: `probe.test.tsx` renders one and requires
 * this markup to carry every class and attribute it writes, and no other.
 *
 * THE CONTAINER IS SIZED AT THE AXIS PLUS SEVEN `--col-min` COLUMNS, which is the narrowest width the policy
 * supports and the width a title is tightest in. The seven columns then land one hairline short of `--col-min` each,
 * so every box the reading reports is a real one at a width the product ships. */

import { AXIS_W_PX, DAY_HEADER_H_PX } from "../../src/ui/domain/week-grid/metrics.ts";

/** The element the columns are queried under, so a reading cannot pick up a title case's block. */
const CONTAINER_ID = "week";

/** Where the page reports what it read, one channel per question the gate asks. */
export const COLUMN_READINGS_ID = "column-readings";

/** The global the compiled pointer read is published under. */
export const DRAG_READ_GLOBAL = "syncrDragRead";

/**
 * The dates the seven columns carry, Monday first.
 *
 * The week is the one the drag's own tests use, so both instruments describe the same seven days.
 */
export const WEEK_DATES = [
  "2026-02-09",
  "2026-02-10",
  "2026-02-11",
  "2026-02-12",
  "2026-02-13",
  "2026-02-14",
  "2026-02-15",
] as const;

/**
 * The header each column is drawn with, which is `columnLabel`'s output for the date beside it.
 *
 * Written rather than derived because the formatter reaches the kit's barrel, which a script cannot resolve.
 * `probe.test.tsx` runs the shipped formatter over `WEEK_DATES` and requires this list to equal it, so the two cannot
 * drift in content or in length.
 */
export const WEEK_LABELS = ["MON 09", "TUE 10", "WED 11", "THU 12", "FRI 13", "SAT 14", "SUN 15"];

/** The axis the columns are drawn on: 06:00 to 22:00, the bounds the week screen's own fixture declares. */
export const WEEK_EXTENT = { startMin: 360, endMin: 1320 } as const;

/** The minute a pointer is placed at, 13:00, far enough inside the axis that no rounding reaches an edge. */
export const READ_AT_MIN = 780;

/** `--hairline` on each edge of `.week-grid`, which the seven columns and the axis sit inside. */
const GRID_BORDER_PX = 2;

/** What one column reported about itself, and what the shipped read answered for a pointer over it. */
export interface ColumnReading {
  readonly index: number;
  /** The date this column stands for, so a finding names the day a read landed in. */
  readonly date: string;
  readonly leftPx: number;
  readonly rightPx: number;
  readonly topPx: number;
  readonly bottomPx: number;
  /** The quarter a pointer at this column's own horizontal centre names, read against THIS column's box. */
  readonly ownMin: number | null;
  /** The same pointer position read against the PREVIOUS column's box. Null for the first column. */
  readonly fromPreviousMin: number | null;
  /** The same pointer position read against the NEXT column's box. Null for the last column. */
  readonly fromNextMin: number | null;
  /** This column's own box read at its right edge, and one pixel past it. */
  readonly atRightEdgeMin: number | null;
  readonly pastRightEdgeMin: number | null;
  /** And at its left edge, and one pixel before it. */
  readonly atLeftEdgeMin: number | null;
  readonly beforeLeftEdgeMin: number | null;
}

/** What the page reports, or the reason it could report nothing. */
export interface ColumnReport {
  readonly atMin: number;
  readonly clientY: number;
  readonly columns: readonly ColumnReading[];
  /** Present only where the page could measure nothing at all, which is a fault in the instrument. */
  readonly error?: string | undefined;
}

export interface WeekColumnsRequest {
  /** Pixels per minute on the reference display, which the page computes and this section is drawn at. */
  readonly pxPerMin: number;
  /** `--col-min`, the width each column is pinned to. */
  readonly columnPx: number;
}

export interface WeekColumns {
  /** The container rule, which is what makes the two width regimes agree. */
  readonly style: string;
  readonly html: string;
  /** The page-side reading, which runs after the compiled read has been loaded. */
  readonly script: string;
  readonly widthPx: number;
  readonly heightPx: number;
}

const PLACES = 3;

export function weekColumns({ pxPerMin, columnPx }: WeekColumnsRequest): WeekColumns {
  const canvasHeightPx = (WEEK_EXTENT.endMin - WEEK_EXTENT.startMin) * pxPerMin;
  const widthPx = AXIS_W_PX + WEEK_LABELS.length * columnPx + GRID_BORDER_PX;

  return {
    style: `#${CONTAINER_ID} { width: ${String(widthPx)}px }`,
    html: markup(canvasHeightPx),
    script: readingScript(pxPerMin),
    widthPx,
    heightPx: DAY_HEADER_H_PX + canvasHeightPx + GRID_BORDER_PX,
  };
}

/* `WeekGrid`'s frame, `TimeAxis`'s frame and seven of `DayColumn`'s, in the nesting and with the class lists React
 * writes them in. A day holding nothing renders a count of zero, which is what these columns hold. */
function markup(canvasHeightPx: number): string {
  const height = `height:${canvasHeightPx.toFixed(PLACES)}px`;
  const columns = WEEK_LABELS.map(
    (label) =>
      `<div class="week-day max-narrow:shrink-0 max-narrow:grow-0 max-narrow:basis-col-min">` +
      `<div class="week-day__head">${label}<span class="week-day__count">0</span></div>` +
      `<div class="week-day__canvas" style="${height}"></div>` +
      `</div>`,
  ).join("");

  return (
    `<div id="${CONTAINER_ID}">` +
    `<div class="week-grid max-narrow:overflow-x-auto">` +
    `<div class="week-grid__axis"><div class="week-grid__axis-head"></div>` +
    `<div class="week-grid__axis-canvas" style="${height}"></div></div>` +
    `<div class="week-grid__days">${columns}</div>` +
    `</div></div>`
  );
}

/* THE THREE READS PER COLUMN, AND WHY EACH IS THERE.
 *
 * One pointer position per column, at that column's own horizontal centre and at a shared Y, read against three
 * boxes: its own, its predecessor's and its successor's. Its own answers the quarter, because the columns share one
 * row and the same Y is the same quarter in all seven. Its neighbours' answer nothing, because the position is outside
 * their boxes, and that is what makes a release over the next column state no placement in the column it left.
 *
 * The edge reads bound the refusal from both sides at one pixel: the comparison is inclusive, so the right edge itself
 * still names a quarter and one pixel past it names none.
 *
 * `pointAt` reads `origin.canvas`, `live.extent` and `live.pxPerMin` and nothing else, so those three are what this
 * stand-in supplies. A read that grew a fourth dependency would answer null here rather than answering wrongly. */
function readingScript(pxPerMin: number): string {
  return `
  (() => {
    const report = (value) => {
      document.getElementById(${JSON.stringify(COLUMN_READINGS_ID)}).textContent = JSON.stringify(value);
    };
    const read = window.${DRAG_READ_GLOBAL};
    if (typeof read !== "function") {
      report({ error: "the compiled pointer read did not load, so no column was measured" });
      return;
    }
    const canvases = [...document.querySelectorAll("#${CONTAINER_ID} .week-day__canvas")];
    if (canvases.length === 0) {
      report({ error: "the page rendered no day column canvas, so no column was measured" });
      return;
    }
    const dates = ${JSON.stringify(WEEK_DATES)};
    const live = { extent: ${JSON.stringify(WEEK_EXTENT)}, pxPerMin: ${String(pxPerMin)} };
    const atMin = ${String(READ_AT_MIN)};
    const minuteAt = (canvas, clientX, clientY) => {
      const point = read(clientX, clientY, { canvas }, live);
      return point === null ? null : point.min;
    };
    const boxes = canvases.map((canvas) => canvas.getBoundingClientRect());
    const clientY = boxes[0].top + (atMin - live.extent.startMin) * live.pxPerMin;
    report({
      atMin,
      clientY,
      columns: canvases.map((canvas, index) => {
        const box = boxes[index];
        const clientX = (box.left + box.right) / 2;
        return {
          index,
          date: dates[index] ?? null,
          leftPx: box.left,
          rightPx: box.right,
          topPx: box.top,
          bottomPx: box.bottom,
          ownMin: minuteAt(canvas, clientX, clientY),
          fromPreviousMin: index === 0 ? null : minuteAt(canvases[index - 1], clientX, clientY),
          fromNextMin:
            index === canvases.length - 1 ? null : minuteAt(canvases[index + 1], clientX, clientY),
          atRightEdgeMin: minuteAt(canvas, box.right, clientY),
          pastRightEdgeMin: minuteAt(canvas, box.right + 1, clientY),
          atLeftEdgeMin: minuteAt(canvas, box.left, clientY),
          beforeLeftEdgeMin: minuteAt(canvas, box.left - 1, clientY),
        };
      }),
    });
  })();
`;
}
