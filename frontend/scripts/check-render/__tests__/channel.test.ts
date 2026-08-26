/* THE CHANNEL TABLE'S OWN GUARDS, HELD WITHOUT A BROWSER.
 *
 * Every lookup the table makes stands for composition rules it exists to measure, so a case that goes missing must
 * be a FINDING rather than a silent skip: these tests remove each state case in turn and require the loss to be
 * named. The line weighings are shape-checked for the same reason -- a truncated report is an instrument fault, not
 * a crash. */

import { describe, expect, it } from "vitest";

import { channelTable, parseLineWeights } from "../check.ts";
import { CASES, geometryOf, type PageReading } from "../page.ts";

const cases = geometryOf(CASES);

/** A reading carrying only what the table's lookups touch, keyed to one case id. */
function readingFor(id: string): PageReading {
  return {
    id,
    titleTopPx: 4,
    titleLeftPx: 5,
    lineHeightPx: 13.8,
    maxHeightPx: 13.8,
    firstLineWidthPx: 100,
    borderTopWidth: "2px",
    borderTopColor: "rgb(1, 2, 3)",
    borderRightWidth: "0px",
    borderRightColor: "rgb(1, 2, 3)",
    borderBottomWidth: "1px",
    borderBottomColor: "rgb(1, 2, 3)",
    borderBottomStyle: "solid",
    borderLeftWidth: "3px",
    borderLeftColor: "rgba(0, 0, 0, 0)",
    backgroundColor: "rgb(4, 5, 6)",
    hatchBackgroundImage: null,
  };
}

const readings = cases.map((_, index) => readingFor(`capped-${String(index)}`));

describe("the channel table's own cases", () => {
  it("measures every rule with the full case table present", () => {
    const missing = channelTable(cases, readings).filter((finding) =>
      finding.message.includes("no case stands"),
    );

    expect(missing).toEqual([]);
  });

  /* Each removal stands for the accident the guard exists for: a state shape or origin changed and its case went
   * with it. The table must name the loss rather than quietly retire the rules that referenced it. */
  for (const label of [
    "conflicted alone",
    "selected alone",
    "conflicted and selected",
    "split at rest",
    "split and selected",
    "proposal target",
    "anchor block",
  ]) {
    it(`names it when the ${label} case goes missing`, () => {
      const without = cases.filter((each) => {
        const states = JSON.stringify(each.states ?? {});
        if (label === "anchor block") return each.origin !== "anchor";
        if (label === "conflicted alone") return states !== JSON.stringify({ conflicted: true });
        if (label === "selected alone") return states !== JSON.stringify({ selected: true });
        if (label === "conflicted and selected")
          return states !== JSON.stringify({ conflicted: true, selected: true });
        if (label === "split at rest") return states !== JSON.stringify({ split: true });
        if (label === "split and selected")
          return states !== JSON.stringify({ split: true, selected: true });
        return states !== JSON.stringify({ proposalTarget: true });
      });
      const renumbered = without.map((_, index) => readingFor(`capped-${String(index)}`));

      const findings = channelTable(without, renumbered);
      expect(
        findings.some(
          (finding) =>
            finding.message.includes("no case stands") && finding.message.startsWith(label),
        ),
        `expected ${label}'s loss to be reported`,
      ).toBe(true);
    });
  }
});

describe("the line weighings' parse", () => {
  const valid = {
    atRest: { hour: "rgb(1, 2, 3)", quarter: "rgb(4, 5, 6)" },
    dragging: { hour: "rgb(1, 2, 3)", quarter: "rgb(1, 2, 3)" },
  };

  it("takes a well-formed report", () => {
    expect(parseLineWeights(JSON.stringify(valid))).toEqual(valid);
  });

  it("refuses what it cannot trust rather than crashing on it", () => {
    expect(parseLineWeights("")).toBeNull();
    expect(parseLineWeights("not json")).toBeNull();
    expect(parseLineWeights("[1, 2]")).toBeNull();
    /* A report missing either weighing used to pass an unchecked cast and crash on the missing field. */
    expect(parseLineWeights(JSON.stringify({ atRest: valid.atRest }))).toBeNull();
    expect(
      parseLineWeights(JSON.stringify({ ...valid, dragging: { hour: "rgb(1,2,3)" } })),
    ).toBeNull();
  });
});
