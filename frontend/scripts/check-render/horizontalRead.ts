/* WHAT THE SEVEN COLUMNS' READINGS HAVE TO SAY, AND WHICH FAULT EACH FINDING IS ABOUT.
 *
 * Three questions, and they fail apart on purpose. Whether the page could measure anything at all is a fault in the
 * INSTRUMENT: the compiled read did not load, or no column rendered. Whether there are seven ordered, non-overlapping
 * boxes is a fault in the FIXTURE: seven identical columns would make "over the next column" mean nothing, which is
 * exactly the blindness a stubbed box has. Only the third is a fault in the PRODUCT, and it is the one the gate is for:
 * a position over the next column, read against the box of the column the drag began in, must name no quarter at all.
 *
 * Reading them apart is what keeps a red honest. A page that failed to compile would otherwise redden the same check as
 * a drag that placed a block in a day the reader had left. */

import path from "node:path";

import { frontendRoot } from "../lib/paths.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { WEEK_DATES, type ColumnReading, type ColumnReport } from "./weekColumns.ts";

const READ = path.join(frontendRoot, "src", "ui", "domain", "week-grid", "useDiscreteDrag.ts");
const PAGE = path.join(frontendRoot, "scripts", "check-render", "weekColumns.ts");

export function horizontalRead(text: string): CheckOutcome {
  const report = parse(text);
  if (report === null || report.error !== undefined) {
    return {
      findings: [
        {
          file: PAGE,
          check: "column-readings",
          message:
            `the page reported no column geometry, so the horizontal axis of the drag was not measured: ` +
            `${report?.error ?? "the readings could not be parsed"}. Nothing here is a claim about the drag.`,
        },
      ],
      notes: [],
    };
  }

  const columns = report.columns;
  const findings = [
    ...census(columns),
    ...boxes(columns),
    ...quarters(columns, report.atMin),
    ...neighbours(columns, report.atMin),
  ];
  return { findings, notes: notesOf(report) };
}

/* SEVEN, EXACTLY. Six columns would leave a day of the week unmeasured and eight would put a boundary where the product
 * has none, and a count read from the page rather than from the fixture is what catches either. */
function census(columns: readonly ColumnReading[]): Finding[] {
  if (columns.length === WEEK_DATES.length) return [];
  return [
    {
      file: PAGE,
      check: "column-census",
      message:
        `the page rendered ${String(columns.length)} day column(s) and a week has ` +
        `${String(WEEK_DATES.length)}. The horizontal read is only observable across a boundary between two real ` +
        "columns, so a page with any other number measures something else.",
    },
  ];
}

/* SEVEN DISTINCT BOXES, IN ORDER, NONE EMPTY. This is the whole difference between this page and a test: a stubbed box
 * is the same box for every canvas, so a position "over the next column" is over the origin column too and the read
 * cannot be wrong. A collapsed or duplicated column here would reintroduce that blindness silently. */
function boxes(columns: readonly ColumnReading[]): Finding[] {
  const findings: Finding[] = [];
  for (const [index, column] of columns.entries()) {
    const width = column.rightPx - column.leftPx;
    if (width <= 0) {
      findings.push({
        file: PAGE,
        check: "column-boxes",
        message:
          `${column.date} is ${width.toFixed(2)}px wide, so it holds no position a pointer can be over. ` +
          "A column that collapses reads as the column beside it.",
      });
    }
    const before = columns[index - 1];
    if (before === undefined) continue;
    if (column.leftPx < before.rightPx || column.leftPx <= before.leftPx) {
      findings.push({
        file: PAGE,
        check: "column-boxes",
        message:
          `${column.date} spans ${column.leftPx.toFixed(2)}..${column.rightPx.toFixed(2)}px and ` +
          `${before.date} spans ${before.leftPx.toFixed(2)}..${before.rightPx.toFixed(2)}px, which do not sit ` +
          "side by side. Two columns sharing a box is what makes a stubbed geometry unable to see this axis at all.",
      });
    }
  }
  return findings;
}

/* WHAT A COLUMN'S OWN BOX SAYS. The seven canvases share one row, so the same Y is the same quarter in every one of
 * them, and it is the quarter the page placed the pointer at. A null here would make every refusal below meaningless:
 * a read that names nothing anywhere refuses the next column for the wrong reason. */
function quarters(columns: readonly ColumnReading[], atMin: number): Finding[] {
  const findings: Finding[] = [];
  for (const column of columns) {
    if (column.ownMin === atMin) continue;
    findings.push({
      file: READ,
      check: "pointer-read",
      message:
        `a pointer at ${column.date}'s own horizontal centre, at the pixel its own box puts ${String(atMin)} ` +
        `minutes at, was read against that box as ${String(column.ownMin)}. A column's own position has to name ` +
        "its own quarter, or nothing else measured here means anything.",
    });
  }
  return findings;
}

/* THE AXIS THIS PAGE EXISTS FOR. The pointer sits over one column; the boxes either side of it are asked what that
 * position names and must answer nothing. Reading it against the column the drag began in is how a drag over Tuesday
 * came to pin a block to Monday, and the edge reads bound the refusal at one pixel on both sides so the bound is
 * measured rather than assumed. */
function neighbours(columns: readonly ColumnReading[], atMin: number): Finding[] {
  const findings: Finding[] = [];
  for (const [index, column] of columns.entries()) {
    const before = columns[index - 1];
    if (before !== undefined && column.fromPreviousMin !== null) {
      findings.push(crossed(column, before, column.fromPreviousMin));
    }
    const after = columns[index + 1];
    if (after !== undefined && column.fromNextMin !== null) {
      findings.push(crossed(column, after, column.fromNextMin));
    }
    findings.push(...edges(column, atMin));
  }
  return findings;
}

function crossed(over: ColumnReading, against: ColumnReading, stated: number): Finding {
  return {
    file: READ,
    check: "horizontal-read",
    message:
      `a pointer over ${over.date}, at x=${((over.leftPx + over.rightPx) / 2).toFixed(2)}px, was read against ` +
      `${against.date}'s box (${against.leftPx.toFixed(2)}..${against.rightPx.toFixed(2)}px) and named ` +
      `${String(stated)} minutes. A position outside a column's box is over ANOTHER column, and reading it against ` +
      "the one the drag began in states a placement in a day the reader had left.",
  };
}

/* THE EXCLUSION'S TWO EDGES, at one pixel. The comparison is inclusive, so the edge itself still names a quarter: an
 * edge read that answered nothing would mean the refusal below was catching the boundary rather than the column beside
 * it. */
function edges(column: ColumnReading, atMin: number): Finding[] {
  const cases = [
    { at: "its right edge", stated: column.atRightEdgeMin, expected: atMin },
    { at: "one pixel past its right edge", stated: column.pastRightEdgeMin, expected: null },
    { at: "its left edge", stated: column.atLeftEdgeMin, expected: atMin },
    { at: "one pixel before its left edge", stated: column.beforeLeftEdgeMin, expected: null },
  ];
  return cases
    .filter((each) => each.stated !== each.expected)
    .map((each) => ({
      file: READ,
      check: "horizontal-read",
      message:
        `${column.date} read at ${each.at} named ${String(each.stated)} and the bound puts ` +
        `${String(each.expected)} there. The box is inclusive of its own edges, so a pixel inside names the ` +
        "quarter and a pixel outside names nothing.",
    }));
}

/** What the readings cover, derived from them, so a green run says how much it looked at. */
function notesOf(report: ColumnReport): string[] {
  const columns = report.columns;
  const boundaries = Math.max(columns.length - 1, 0);
  const widths = columns.map((column) => (column.rightPx - column.leftPx).toFixed(2)).join(", ");
  return [
    `${String(columns.length)} real day column(s) at ${widths}px, a pointer at ` +
      `${String(report.atMin)} minutes on y=${report.clientY.toFixed(2)}`,
    `${String(boundaries * 2)} neighbour read(s) across ${String(boundaries)} boundary(ies), ` +
      `${String(columns.length * 2)} edge read(s) and their ${String(columns.length * 2)} control(s)`,
  ];
}

function parse(text: string): ColumnReport | null {
  if (text.trim() === "") return null;
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null ? (parsed as ColumnReport) : null;
  } catch {
    return null;
  }
}
