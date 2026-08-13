/* THE WIDTH POLICY, HELD AGAINST THE LEDGER THAT DERIVED IT.
 *
 * The floor is 17 CHARACTERS PER DAY COLUMN and every threshold is derived from it rather than chosen. That
 * derivation is the one part of this component that a computed ledger caught: 1536px with the panel open yields 17
 * characters and 1440px yields 15, which is why --bp-wide is 1536 and not the 1440 a first draft assumed.
 *
 * So the assertions are the ARITHMETIC, from the tokens, rather than a table of expected pixels. A retuned sidebar,
 * panel or column floor then fails here, which is what a derived breakpoint means: the value is not a preference.
 * The ledger itself lives in `src/testing/widthLedger.ts`, because where the detail panel mounts is worked back
 * from the same figures and a second copy of them would let one of the two suites pass against a retuned sidebar.
 *
 * WHAT THIS FILE ASSERTS ABOUT THE RAIL is that the mechanism is correct and available: the rail's width is a
 * token, the threshold is the theme's own mirror of --bp-wide, and the utility that pairs them compiles. What the
 * reader reaches through the rail, and where the panel goes when they do, belongs to the surface that mounts it. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { compileUtilities } from "../../../../testing/compileTheme";
import { componentsNaming } from "../../../../testing/kitSources";
import { domainDir } from "../../../../testing/kitStylesheets";
import {
  CHARACTER_FLOOR,
  CHARACTER_PX,
  CHROME_PX,
  layoutPixels as pixels,
  layoutToken,
} from "../../../../testing/widthLedger";

describe("the floor of 17 characters", () => {
  it("needs the day column --col-min declares, and --col-min is that figure rounded up", async () => {
    const needed = CHARACTER_FLOOR * CHARACTER_PX + CHROME_PX;

    expect(needed).toBeCloseTo(134.3, 1);
    expect(await pixels("--col-min")).toBeGreaterThanOrEqual(needed);
  });

  it("is met at --bp-wide with the panel OPEN, which is why 1536 is the threshold", async () => {
    const grid =
      (await pixels("--bp-wide")) - (await pixels("--w-sidebar")) - (await pixels("--w-detail"));

    expect(Math.floor(grid / 7)).toBeGreaterThanOrEqual(
      Math.floor(CHARACTER_FLOOR * CHARACTER_PX + CHROME_PX),
    );
  });

  it("is NOT met at 1440 with the panel open, which is what the ledger caught", async () => {
    const grid = 1440 - (await pixels("--w-sidebar")) - (await pixels("--w-detail"));

    expect(Math.floor(grid / 7)).toBeLessThan(CHARACTER_FLOOR * CHARACTER_PX + CHROME_PX);
  });

  it("is met at --bp-compact with the panel CLOSED, which is the pairing shipped there", async () => {
    const grid =
      (await pixels("--bp-compact")) -
      (await pixels("--w-sidebar")) -
      (await pixels("--w-detail-closed"));

    expect(Math.floor(grid / 7)).toBeGreaterThanOrEqual(
      Math.floor(CHARACTER_FLOOR * CHARACTER_PX + CHROME_PX),
    );
  });
});

describe("the grid absorbs the surplus", () => {
  it("gives every day column an equal share of whatever is left", async () => {
    const declared: string[] = [];
    parse(await readFile(path.join(domainDir, "week-grid", "grid.css"), "utf8")).walkRules(
      (rule) => {
        if (rule.selector !== ".week-day") return;
        rule.walkDecls((declaration) => {
          declared.push(`${declaration.prop}: ${declaration.value}`);
        });
      },
    );

    expect(declared).toContain("flex: 1 1 0");
    expect(declared).toContain("min-width: 0");
  });

  it("keeps the axis fixed, so the surplus goes to the columns and not to the gutter", async () => {
    const source = await readFile(path.join(domainDir, "week-grid", "grid.css"), "utf8");

    expect(source).toContain("flex: 0 0 auto");
    expect(source).toContain("width: var(--axis-w)");
  });
});

describe("below --bp-compact the grid scrolls instead of narrowing", () => {
  it("names the threshold ONCE, through the theme's own mirror of the token", async () => {
    const compiled = await compileUtilities([
      "max-narrow:overflow-x-auto",
      "max-narrow:basis-col-min",
    ]);
    const threshold = await layoutToken("--bp-compact");

    expect(compiled).toContain(`@media (width < ${threshold})`);
    expect(compiled).toContain("flex-basis: var(--col-min)");
  });

  it("is where the grid and the columns both say so, rather than in a raw length", async () => {
    const grid = await componentsNaming("max-narrow:overflow-x-auto", domainDir);
    const column = await componentsNaming("max-narrow:basis-col-min", domainDir);

    expect(grid).toEqual(["week-grid/WeekGrid.tsx"]);
    expect(column).toEqual(["week-grid/DayColumn.tsx"]);
  });

  it("keeps the axis sticky, so the squeeze is navigable rather than blind", async () => {
    const source = await readFile(path.join(domainDir, "week-grid", "grid.css"), "utf8");

    expect(source).toContain("position: sticky");
  });
});

/* THE PANEL CLOSES TO A RAIL RATHER THAN NARROWING, because a narrower panel cannot hold a reason and a narrower grid
 * cannot hold a title. The panel itself arrives with whatever owns the detail panel; what is asserted here is that the
 * rail is a token rather than a length, and that the utility pairing it with --bp-wide compiles. */
describe("the detail panel's rail", () => {
  it("is one control height, which is 26px, rather than a length of its own", async () => {
    expect(await layoutToken("--w-detail-closed")).toBe("var(--h-control)");
    expect(await pixels("--h-control")).toBe(26);
  });

  it("pairs with --bp-wide through a utility that compiles", async () => {
    const compiled = await compileUtilities(["max-wide:w-detail-closed"]);
    const threshold = await layoutToken("--bp-wide");

    expect(compiled).toContain(`@media (width < ${threshold})`);
    expect(compiled).toContain("width: var(--w-detail-closed)");
  });
});
