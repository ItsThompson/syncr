/* THE MIRROR, HELD AGAINST THE PYTHON FIXTURE IT MIRRORS.
 *
 * `syncr_domain.fixtures.dst_weeks` is the one set of DST dates every layer's claims are made against, and the
 * frontend cannot import it. So the figures are duplicated in `testing/dstWeeks.ts` and this file reads the Python
 * source and requires each literal to match. A retuned fixture, a corrected transition date or a renamed field then
 * fails here rather than leaving the grid asserting a 23-hour day on a date the domain thinks is 24.
 *
 * The Python is read as TEXT rather than parsed, because what is being compared is a set of literals: the fixture's
 * own docstring says every instant there is a literal deliberately, so that a test asserting `week_span` against it
 * is a check rather than a restatement. The same reasoning applies one language over. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { DST_WEEKS, FALL_BACK, LONDON, SPRING_FORWARD, type DstWeek } from "../dstWeeks";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const FIXTURE = path.join(
  repoRoot,
  "packages",
  "syncr-domain",
  "src",
  "syncr_domain",
  "fixtures",
  "dst_weeks.py",
);

const source = await readFile(FIXTURE, "utf8");

/** Two digits, so a month and a day compare with the ISO literal rather than with a Python integer. */
const pad = (part: string): string => part.padStart(2, "0");

/** The body of one `DstWeek(...)` call in the Python fixture. */
function pythonWeek(constant: string): string {
  const match = new RegExp(`${constant} = DstWeek\\(([\\s\\S]*?)\\n\\)`).exec(source);
  if (match === null) throw new Error(`${constant} is not a DstWeek in ${FIXTURE}`);
  return match[1];
}

/** A `datetime(...)` argument as an ISO instant, so it compares with the TypeScript literal. */
function instantOf(body: string, field: string): string {
  const pattern = new RegExp(
    `${field}=(?:Interval\\(\\s*)?datetime\\((\\d+), (\\d+), (\\d+), (\\d+), (\\d+), tzinfo=UTC\\)`,
  );
  const match = pattern.exec(body);
  if (match === null) throw new Error(`no datetime for ${field}`);
  const [, year, month, day, hour, minute] = match;
  return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:00Z`;
}

/** The SECOND datetime of an `Interval(...)`, which is the field's end. */
function intervalEndOf(body: string, field: string): string {
  const pattern = new RegExp(
    `${field}=Interval\\(\\s*datetime\\([^)]*\\),\\s*datetime\\((\\d+), (\\d+), (\\d+), (\\d+), (\\d+), tzinfo=UTC\\)`,
  );
  const match = pattern.exec(body);
  if (match === null) throw new Error(`no interval end for ${field}`);
  const [, year, month, day, hour, minute] = match;
  return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:00Z`;
}

function minutesOf(body: string, field: string): number {
  const match = new RegExp(`${field}=(\\d+) \\* 60`).exec(body);
  if (match === null) throw new Error(`no minute figure for ${field}`);
  return Number(match[1]) * 60;
}

function isoWeekOf(body: string): string {
  const match = /iso_week=IsoWeek\((\d+), (\d+)\)/.exec(body);
  if (match === null) throw new Error("no iso_week");
  return `${match[1]}-W${match[2].padStart(2, "0")}`;
}

function transitionDateOf(body: string): string {
  const match = /transition_date=date\((\d+), (\d+), (\d+)\)/.exec(body);
  if (match === null) throw new Error("no transition_date");
  return `${match[1]}-${pad(match[2])}-${pad(match[3])}`;
}

describe.each([
  ["SPRING_FORWARD", SPRING_FORWARD],
  ["FALL_BACK", FALL_BACK],
])("%s mirrors the domain's fixture", (constant, week: DstWeek) => {
  const body = pythonWeek(constant);

  it("names the same ISO week and transition date", () => {
    expect(week.isoWeek).toBe(isoWeekOf(body));
    expect(week.transitionDate).toBe(transitionDateOf(body));
  });

  it("carries the same week span, which is 167 or 169 hours", () => {
    expect(week.spanStart).toBe(instantOf(body, "span"));
    expect(week.spanEnd).toBe(intervalEndOf(body, "span"));
    expect(week.spanMinutes).toBe(minutesOf(body, "span_minutes"));
  });

  it("carries the same local transition day, which is 23 or 25 hours", () => {
    expect(week.transitionDayStart).toBe(instantOf(body, "local_transition_day"));
    expect(week.transitionDayEnd).toBe(intervalEndOf(body, "local_transition_day"));
    expect(week.transitionDayMinutes).toBe(minutesOf(body, "local_transition_day_minutes"));
  });

  it("carries the same Sunday-night frame, which ends inside the following week", () => {
    expect(week.sundayNightFrameStart).toBe(instantOf(body, "sunday_night_frame"));
    expect(week.sundayNightFrameEnd).toBe(intervalEndOf(body, "sunday_night_frame"));
  });

  it("holds the transition date as its seventh column, and seven dates in all", () => {
    expect(week.dates).toHaveLength(7);
    expect(week.dates.at(-1)).toBe(week.transitionDate);
  });
});

describe("the fixture's own zone", () => {
  it("is the one the domain names", () => {
    expect(LONDON).toBe(/LONDON: ZoneId = "([^"]+)"/.exec(source)?.[1]);
  });

  it("is the zone both weeks are read in", () => {
    for (const week of DST_WEEKS) expect(week.zone).toBe(LONDON);
  });
});
