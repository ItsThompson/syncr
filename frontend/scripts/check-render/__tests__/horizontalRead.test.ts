/* THE COLUMN READINGS' OWN CHECKS, WITHOUT A BROWSER.
 *
 * Every one of the five checks is exercised end to end by a plant against `lint:render`, which is stronger evidence
 * than this file can give for the four that need a real layout. What a plant cannot reach is a page that reports
 * something parseable and WRONG: the page-side reading is a template string that no type checker and no linter reads,
 * so a defect there arrives as a report with a figure missing. Before the shape was checked, that took the whole gate
 * down with a `TypeError` inside the first check and the nine title cases with it, which is worse than a mis-named red
 * because there is no finding at all.
 *
 * So the cases below are mostly about the channel, and one per family to hold the names apart: an instrument fault, a
 * fixture fault and a product fault must never arrive under the same check name. */

import { describe, expect, it } from "vitest";

import { horizontalRead } from "../horizontalRead.ts";
import { READ_AT_MIN, WEEK_DATES, WEEK_EXTENT, type ColumnReading } from "../weekColumns.ts";

/** The width the seven columns measure in the browser, and the border between two of them. */
const COLUMN_WIDTH_PX = 136.14;
const BORDER_PX = 1;
const FIRST_LEFT_PX = 57;

/** One column as the page reports it when everything is right: its own box names its own quarter, its neighbours none. */
function reading(index: number, over: Partial<ColumnReading> = {}): ColumnReading {
  const leftPx = FIRST_LEFT_PX + index * (COLUMN_WIDTH_PX + BORDER_PX);
  return {
    index,
    date: WEEK_DATES[index],
    leftPx,
    rightPx: leftPx + COLUMN_WIDTH_PX,
    topPx: 3989,
    bottomPx: 4823.65,
    ownMin: READ_AT_MIN,
    fromPreviousMin: null,
    fromNextMin: null,
    atRightEdgeMin: READ_AT_MIN,
    pastRightEdgeMin: null,
    atLeftEdgeMin: READ_AT_MIN,
    beforeLeftEdgeMin: null,
    ...over,
  };
}

function report(columns: readonly ColumnReading[]): string {
  return JSON.stringify({ atMin: READ_AT_MIN, clientY: 4354.17, columns });
}

const green = (): string => report(WEEK_DATES.map((_date, index) => reading(index)));

const namesOf = (text: string): string[] =>
  horizontalRead(text).findings.map((finding) => finding.check);

describe("a reading the gate cannot use", () => {
  it("reports the channel rather than throwing when a figure is missing", () => {
    /* Parseable, an object, and wrong: the shape a defect in the page's own script produces. */
    const malformed = JSON.stringify({ atMin: READ_AT_MIN, clientY: 1, columns: [{ index: 0 }] });

    expect(namesOf(malformed)).toEqual(["column-readings"]);
  });

  it("reports the channel when the report carries no column list at all", () => {
    expect(namesOf(JSON.stringify({ atMin: 780, clientY: 1 }))).toEqual(["column-readings"]);
  });

  it.each([
    ["nothing", ""],
    ["text that is not JSON", "<html>"],
    ["a JSON value that is not an object", "42"],
  ])("reports the channel for %s", (_case, text) => {
    expect(namesOf(text)).toEqual(["column-readings"]);
  });

  it("carries the page's own sentence when the page says why it measured nothing", () => {
    const said = "the compiled pointer read did not load, so no column was measured";

    const [finding] = horizontalRead(JSON.stringify({ error: said })).findings;

    expect(finding.check).toBe("column-readings");
    expect(finding.message).toContain(said);
  });

  it("claims no coverage where it measured nothing, so a note cannot outlive its reading", () => {
    expect(horizontalRead("").notes).toEqual([]);
  });
});

describe("the reading a green browser run produces", () => {
  it("states no finding", () => {
    expect(horizontalRead(green()).findings).toEqual([]);
  });

  it("derives its coverage from the columns the page reported", () => {
    expect(horizontalRead(green()).notes[1]).toContain(
      "12 neighbour read(s) across 6 boundary(ies)",
    );
  });
});

/* ONE CASE PER FAMILY, to hold the names apart. What each one MEANS is measured against a browser by the plants; what
 * is asserted here is that a fixture fault and a product fault cannot arrive under one name. */
describe("each fault arrives under its own name", () => {
  it("names the census where a week is not seven columns", () => {
    const six = WEEK_DATES.slice(0, 6).map((_date, index) => reading(index));

    expect(namesOf(report(six))).toEqual(["column-census"]);
  });

  it("names the boxes where two columns share one", () => {
    const stacked = WEEK_DATES.map((_date, index) =>
      reading(index, { leftPx: FIRST_LEFT_PX, rightPx: FIRST_LEFT_PX + COLUMN_WIDTH_PX }),
    );

    expect(new Set(namesOf(report(stacked)))).toEqual(new Set(["column-boxes"]));
  });

  it("names the pointer read where a column's own box names no quarter", () => {
    /* Only `ownMin` is nulled here, so the family is isolated: a browser plant that stops the read answering at all
     * takes the inside-edge controls with it and reddens both names. */
    const columns = WEEK_DATES.map((_date, index) => reading(index, { ownMin: null }));

    expect(new Set(namesOf(report(columns)))).toEqual(new Set(["pointer-read"]));
  });

  it("names the horizontal read where a neighbour's box named the position", () => {
    const columns = WEEK_DATES.map((_date, index) =>
      index === 3 ? reading(index, { fromPreviousMin: READ_AT_MIN }) : reading(index),
    );

    expect(namesOf(report(columns))).toEqual(["horizontal-read"]);
  });

  it("reads the axis the page reports rather than one of its own", () => {
    /* The extent is the page's, so a case here cannot drift from the geometry the browser was measured at. */
    expect(WEEK_EXTENT.startMin).toBeLessThan(READ_AT_MIN);
    expect(WEEK_EXTENT.endMin).toBeGreaterThan(READ_AT_MIN);
  });
});
