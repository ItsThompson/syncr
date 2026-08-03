/* THE CONTRAST LEDGER FOR THE CONTROL BORDER, computed rather than asserted.
 *
 * A control border is the only thing marking where the control begins, which makes it an indicator under the
 * 3:1 rule rather than decoration. The design language records that --rule-strong measures 2.65:1 on
 * --paper-raised and is therefore BANNED on a control, while --rule-control measures 5.28:1.
 *
 * Those two figures are the reason `control.css` reads --rule-control, so they are computed here from the
 * token files rather than trusted: `src/testing/contrast.ts` resolves the token chain to a hex, converts to
 * relative luminance, and applies the WCAG formula. A retuned pigment that dropped the border below 3:1 would
 * fail this file, which is what "every number is computed, never asserted" means in a test.
 *
 * BOTH SURFACES ARE MEASURED, not only the expected one. The review checklist asks for a computed ratio
 * against every surface a pair can reach, and a control legitimately sits on --paper as well as on
 * --paper-raised: a field inside a panel is on the raised surface, a field on a page band is on the page. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { srcDir } from "../../testing/compileTheme";
import { INDICATOR_FLOOR, ratioBetween } from "../../testing/contrast";

describe("the control border", () => {
  it("clears the 3:1 indicator floor on the raised surface it normally sits on", async () => {
    const ratio = await ratioBetween("--rule-control", "--paper-raised");

    expect(ratio).toBeGreaterThanOrEqual(INDICATOR_FLOOR);
    expect(ratio.toFixed(2)).toBe("5.28");
  });

  it("clears it on the page surface too, which is the other surface a field can reach", async () => {
    const ratio = await ratioBetween("--rule-control", "--paper");

    expect(ratio).toBeGreaterThanOrEqual(INDICATOR_FLOOR);
    expect(ratio.toFixed(2)).toBe("4.89");
  });

  it("is the token `control.css` reads, and no other", async () => {
    const control = await readFile(path.join(srcDir, "ui", "primitives", "control.css"), "utf8");
    const border = /^\s*border:\s*([^;]+);/m.exec(control);

    expect(border?.[1]).toBe("var(--hairline) solid var(--rule-control)");
  });
});

describe("--rule-strong on a control", () => {
  /* The banned pair, measured. It is in this file because the ban is only meaningful with the number beside
   * it: 2.65:1 is below the indicator floor, which is why a container may use it and a control may not. */
  it("fails the indicator floor, which is why it is banned there", async () => {
    const ratio = await ratioBetween("--rule-strong", "--paper-raised");

    expect(ratio).toBeLessThan(INDICATOR_FLOOR);
    expect(ratio.toFixed(2)).toBe("2.65");
  });

  it("is not reachable from the field family's stylesheet", async () => {
    const control = await readFile(path.join(srcDir, "ui", "primitives", "control.css"), "utf8");
    const declarations = control.replace(/\/\*[\s\S]*?\*\//g, "");

    expect(declarations).not.toContain("--rule-strong");
  });
});

describe("the invalid marker", () => {
  it("clears the indicator floor, because the 3px rule is the whole signal", async () => {
    const ratio = await ratioBetween("--signal-oxide", "--paper-raised");

    expect(ratio).toBeGreaterThanOrEqual(INDICATOR_FLOOR);
  });
});

describe("the ink-filled dialog header", () => {
  /* The one ink surface in the product, and the reason the inverse ring exists: --ink-bright on --ink-deep is
   * invisible, and --paper-raised on it is not. Both figures are the design language's own. */
  it("carries its text at the ratio the token file states", async () => {
    expect((await ratioBetween("--on-ink", "--ink-deep")).toFixed(2)).toBe("14.83");
  });

  it("would lose the standard focus ring, which is why the inverse one is scoped to the container", async () => {
    expect((await ratioBetween("--ink-bright", "--ink-deep")).toFixed(2)).toBe("1.61");
  });

  it("shows the inverse ring at the ratio that made it necessary", async () => {
    expect(await ratioBetween("--paper-raised", "--ink-deep")).toBeGreaterThan(INDICATOR_FLOOR);
  });
});
