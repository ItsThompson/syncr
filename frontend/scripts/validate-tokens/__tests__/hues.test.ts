/* THE AREA RAMP'S HUE LEDGER, AND THE THREE THINGS THIS CHECK REFUSES.
 *
 * The ledger drifted once and the drift was invisible: an earlier version of the pigment comment misreported the
 * tightest pair as 02/03 at 23 degrees, and `docs/design/specimen.html` kept a hardcoded copy while the sheet
 * claimed it computed the result. Reference sheets now derive hue from linked tokens, so the fixtures below plant
 * the shapes that would let a token statement, a sheet ledger, or the ramp's spacing drift.
 *
 * The shipped ramp is asserted too, with the figures the design language states, because a check whose only cases
 * are fixtures says nothing about the pigments that ship. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  ASSIGNMENT_FLOOR,
  SEPARATION_FLOOR,
  adjacentGaps,
  areaHues,
  checkAreaHues,
  firstFourPairs,
  hueOf,
  pigmentFile,
} from "../hues.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string): string => path.join(here, "..", "__fixtures__", name);

const checksOf = (findings: readonly { check: string }[]): string[] => [
  ...new Set(findings.map((finding) => finding.check)),
];

const shipped = async () => areaHues(await readFile(pigmentFile, "utf8"));

describe("the hue of a pigment", () => {
  it.each([
    ["#AB4757", 350.4],
    ["#13746E", 176.3],
    ["#A84476", 330],
  ])("is derived from %s as %s degrees", (hex, hue) => {
    expect(Number(hueOf(hex).toFixed(1))).toBe(hue);
  });

  it("is zero for a grey, which has no hue to read", () => {
    expect(hueOf("#808080")).toBe(0);
  });
});

describe("the shipped ramp", () => {
  it("holds twelve pigments, every one of them a hex", async () => {
    const hues = await shipped();

    expect(hues).toHaveLength(12);
    expect(hues.map((pigment) => pigment.id)).toEqual([
      "01",
      "02",
      "03",
      "04",
      "05",
      "06",
      "07",
      "08",
      "09",
      "10",
      "11",
      "12",
    ]);
  });

  /* The four figures the pigment comment states, computed from the pigments it states them about. */
  it("has the tightest adjacent gaps the design language records", async () => {
    const tightest = adjacentGaps(await shipped())
      .toSorted((one, two) => one.gap - two.gap)
      .slice(0, 4)
      .map((each) => `${each.pair} ${each.gap}`);

    expect(tightest).toEqual(["02/03 19.4", "07/08 20", "12/01 20.4", "06/07 20.6"]);
  });

  it("clears the separation floor, which is what the 07 retune bought", async () => {
    const tightest = adjacentGaps(await shipped()).toSorted((one, two) => one.gap - two.gap)[0];

    expect(tightest.gap).toBeGreaterThanOrEqual(SEPARATION_FLOOR);
  });

  it("deals its first four at least 75 degrees apart, which is what the order is for", async () => {
    const closest = firstFourPairs(await shipped()).toSorted((one, two) => one.gap - two.gap)[0];

    expect(closest).toEqual({ pair: "01/10", gap: 75.3 });
    expect(closest.gap).toBeGreaterThanOrEqual(ASSIGNMENT_FLOOR);
  });

  it("passes the check, and the check says what it measured", async () => {
    const outcome = await checkAreaHues({ pigmentFile, sheetFiles: [] });

    expect(outcome.findings).toEqual([]);
    expect(outcome.notes.some((note) => note.includes("02/03 at 19.4 degrees"))).toBe(true);
    expect(outcome.notes.some((note) => note.includes("01/10 at 75.3 degrees"))).toBe(true);
  });
});

describe("a hue stated beside a pigment", () => {
  it("is refused when it disagrees, which is how the ledger drifted", async () => {
    const outcome = await checkAreaHues({
      pigmentFile: fixture("ramp-drifted.css"),
      sheetFiles: [],
    });

    expect(checksOf(outcome.findings)).toEqual(["area-hue-ledger"]);
    expect(outcome.findings).toHaveLength(12);
  });

  it("names the figure, the pigment's own hue, and what to do about it", async () => {
    const outcome = await checkAreaHues({
      pigmentFile: fixture("ramp-drifted.css"),
      sheetFiles: [],
    });

    expect(outcome.findings[0].message).toContain("355 degrees");
    expect(outcome.findings[0].message).toContain("second copy");
    expect(outcome.findings[0].message).toContain("retune the pigment");
    expect(outcome.findings[0].line).toBe(5);
  });
});

describe("a reference sheet holding its own ledger", () => {
  it("is refused entry by entry, including figures that match the token", async () => {
    const outcome = await checkAreaHues({
      pigmentFile,
      sheetFiles: [fixture("sheet-with-ledger.html")],
    });

    expect(checksOf(outcome.findings)).toEqual(["area-hue-ledger"]);
    expect(outcome.findings).toHaveLength(3);
    expect(outcome.findings.map((finding) => finding.message)).toEqual(
      expect.arrayContaining([
        expect.stringContaining("01 at 355 degrees"),
        expect.stringContaining("02 at 25 degrees"),
        expect.stringContaining("07 at 176 degrees"),
      ]),
    );
  });

  it("names the stored figure and tells the reader to derive it at load", async () => {
    const outcome = await checkAreaHues({
      pigmentFile,
      sheetFiles: [fixture("sheet-with-ledger.html")],
    });

    expect(outcome.findings[0].message).toContain("derive it from the linked Area token at load");
    expect(outcome.findings[0].file).toContain("sheet-with-ledger.html");
  });
});

describe("a ramp two dark colours cannot separate in", () => {
  it("is refused, naming the pair and the floor", async () => {
    const outcome = await checkAreaHues({
      pigmentFile: fixture("ramp-collision.css"),
      sheetFiles: [],
    });

    expect(checksOf(outcome.findings)).toEqual(["area-hue-separation"]);
    expect(outcome.findings[0].message).toContain("01/02");
    expect(outcome.findings[0].message).toContain(`below the ${SEPARATION_FLOOR}`);
    expect(outcome.findings[0].message).toContain("07 retune");
  });
});

describe("a deal order whose first four are crowded", () => {
  it("is refused even though every adjacent gap is legal", async () => {
    const outcome = await checkAreaHues({
      pigmentFile: fixture("ramp-crowded-deal.css"),
      sheetFiles: [],
    });

    expect(checksOf(outcome.findings)).toEqual(["area-hue-assignment"]);
    expect(outcome.findings[0].message).toContain("08/10");
    expect(outcome.findings[0].message).toContain(`below the ${ASSIGNMENT_FLOOR}`);
  });
});
