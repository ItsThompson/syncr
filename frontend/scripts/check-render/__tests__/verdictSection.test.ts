/* THE VERDICT PANEL'S PART OF THE RENDERED-PIXEL GATE, HELD WITHOUT A BROWSER.
 *
 * What a unit suite can hold is everything either side of the rendering: the findings arithmetic that decides
 * whether the fourth tradeoff row straddles the panel's clip, the page carrying the section the gate reads, and
 * the one relation between this page's slot figure and the panel's reserved height token that the whole case
 * depends on. Whether a browser actually composes the affordance at `--verdict-h` is what `npm run lint:render`
 * answers over the built stylesheet. */

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { CASES, geometryOf, PAGE_PITCH_PX, probePage } from "../page.ts";
import {
  CLIP_TOLERANCE_PX,
  parseVerdictReport,
  ROW_COUNT,
  VERDICT_READINGS_ID,
  VERDICT_SECTION,
  verdictFindings,
  type VerdictReport,
} from "../verdictPanel.ts";

const CLIP_AT_PX = 200;

/** A report whose fourth row straddles the clip by twice the tolerance, which is what the shipped token composes:
 * three offer rows held whole, and the fourth straddling. */
function straddling(): VerdictReport {
  return {
    panelBottomPx: CLIP_AT_PX,
    rows: [
      { topPx: 60, bottomPx: 95 },
      { topPx: 95, bottomPx: 130 },
      { topPx: 130, bottomPx: 165 },
      { topPx: CLIP_AT_PX - 5, bottomPx: CLIP_AT_PX + 4 * CLIP_TOLERANCE_PX },
    ],
  };
}

describe("the clipped-edge findings", () => {
  it("pass when the fourth row's top edge is inside the panel and its bottom edge beyond the clip", () => {
    expect(verdictFindings(straddling())).toEqual([]);
  });

  it("fail when the height no longer reaches into the fourth row, which is three rows filling the panel", () => {
    /* The mutation `--verdict-h` shortened past the held rows performs: every row the panel holds sits wholly
     * above the clip, so the scroll affordance is gone even though the rows all rendered. */
    const pushedBelow = straddling();
    const rows = [...pushedBelow.rows!];
    rows[3] = { topPx: CLIP_AT_PX + CLIP_TOLERANCE_PX, bottomPx: CLIP_AT_PX + 40 };

    const findings = verdictFindings({ ...pushedBelow, rows });

    expect(findings).toHaveLength(1);
    expect(findings[0]!.check).toBe("rendered-verdict-affordance");
    expect(findings[0]!.message).toContain("TOP EDGE");
  });

  it("fail when nothing is left to reveal, which is a height grown to hold every row", () => {
    const fullyInside = straddling();
    const rows = [...fullyInside.rows!];
    rows[3] = { topPx: 165, bottomPx: CLIP_AT_PX - CLIP_TOLERANCE_PX };

    const findings = verdictFindings({ ...fullyInside, rows });

    expect(findings).toHaveLength(1);
    expect(findings[0]!.check).toBe("rendered-verdict-affordance");
    expect(findings[0]!.message).toContain("BOTTOM EDGE");
  });

  it("treat a touching edge as no affordance rather than as a pass", () => {
    const touching = straddling();
    const rows = [...touching.rows!];
    rows[3] = { topPx: CLIP_AT_PX, bottomPx: CLIP_AT_PX + 40 };

    expect(verdictFindings({ ...touching, rows })).toHaveLength(1);
  });

  it("refuse to answer on a report that measured nothing, which is an instrument fault and not a pass", () => {
    for (const report of [
      null,
      {},
      { error: "the page rendered no verdict panel" },
      { panelBottomPx: 226 },
    ]) {
      const findings = verdictFindings(report);

      expect(findings).toHaveLength(1);
      expect(findings[0]!.check).toBe("rendered-verdict");
    }
  });

  it("ask for the four rows the case is defined by, and not fewer", () => {
    const threeRows = straddling();

    const findings = verdictFindings({ ...threeRows, rows: threeRows.rows!.slice(0, 3) });

    expect(findings).toHaveLength(1);
    expect(findings[0]!.check).toBe("rendered-verdict");
  });
});

describe("the page's verdict reading", () => {
  it("parses what the page reports, and refuses what it cannot trust", () => {
    const report: VerdictReport = { panelBottomPx: 226, rows: [{ topPx: 100, bottomPx: 240 }] };

    expect(parseVerdictReport(JSON.stringify(report))).toEqual(report);
    expect(parseVerdictReport("")).toBeNull();
    expect(parseVerdictReport("not json")).toBeNull();
    expect(parseVerdictReport("[1,2]")).toBeNull();
  });
});

describe("the section on the page", () => {
  const page = probePage({ bundleName: "bundle.css", cases: geometryOf(CASES) });

  it("is carried by the page, so the gate reads a section the page actually holds", () => {
    expect(page).toContain(VERDICT_SECTION.html);
    expect(page).toContain(VERDICT_SECTION.style);
    expect(page).toContain(`id="${VERDICT_READINGS_ID}"`);
  });

  it("renders exactly the four tradeoff rows the clipped-edge question is asked of", () => {
    expect(VERDICT_SECTION.html.match(/class="verdict-panel__row"/g)).toHaveLength(ROW_COUNT);
  });
});

describe("the page's slot against the panel's reserved height", () => {
  /* THE ONE ARITHMETIC THE WHOLE CASE STANDS ON. The verdict section occupies the page's pitch-sized slot below the
   * columns, and the panel's height comes from the built stylesheet's `--verdict-h`, which this file cannot see at
   * run time. So the token is read out of its sheet here, and the slot is required to be the larger: lower the pitch
   * back to or under the panel's height and the panel's lower edge leaves the window this page is shot at, which no
   * browser-tier run could then redress. */
  it("sizes the slot above --verdict-h, whatever the token says", () => {
    const sheet = readFileSync(
      path.join(import.meta.dirname, "../../../src/ui/domain/verdict-panel/tokens.css"),
      "utf8",
    );
    const declared = /--verdict-h:\s*([\d.]+)px/.exec(sheet);
    expect(declared, "tokens.css declares --verdict-h in px").not.toBeNull();

    expect(PAGE_PITCH_PX).toBeGreaterThan(Number.parseFloat(declared![1]!));
  });
});
