/* THE STACKING LADDER, READ FROM THE TOKEN LAYER AND CROSSED AGAINST THE SHEETS.
 *
 * A stacking order spread across seven component sheets is an order nobody can read: each sheet
 * states one number, and the ordering lives nowhere until a reader reconstructs it. So the ladder
 * is declared once in `src/tokens/layout.css`, and this file holds it to two claims: the rungs
 * ascend, and together they cover every height any kit sheet spends.
 *
 * THE COVERAGE CLAIM IS WHAT BITES. Before the ladder existed this file failed with an empty set;
 * after SR-KIT-11 substitutes the literals, it keeps guarding: a rung renamed without its sheet,
 * or a sheet regaining a raw number the ladder no longer names, breaks the crossing in one
 * direction or the other.
 *
 * The heights are read from the stylesheets rather than restated here, for the same reason
 * `overlayLayers.test.ts` reads them: a copy of the numbers in the test is a third place for the
 * order to disagree with itself. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { scanCss } from "../../scripts/lib/css-scan.ts";
import { filesUnder } from "../../scripts/lib/files.ts";
import { srcDir } from "../testing/compileTheme";
import { domainDir, layoutDir, primitivesDir } from "../testing/kitStylesheets";

/** Every `--z-*` rung the token layer declares, in file order. */
async function ladder(): Promise<{ name: string; value: number }[]> {
  const source = await readFile(path.join(srcDir, "tokens", "layout.css"), "utf8");
  return scanCss(source)
    .declarations.filter((declaration) => declaration.name.startsWith("--z-"))
    .map((declaration) => ({ name: declaration.name, value: Number(declaration.value) }));
}

/** Every `z-index` height the kit's component sheets state, with the sheets that state it. */
async function sheetHeights(): Promise<Map<number, string[]>> {
  const heights = new Map<number, string[]>();
  for (const dir of [primitivesDir, layoutDir, domainDir]) {
    for (const file of await filesUnder(dir, [".css"])) {
      const source = await readFile(file, "utf8");
      for (const match of source.matchAll(/z-index:\s*(\d+)/g)) {
        const value = Number(match[1]);
        heights.set(value, [...(heights.get(value) ?? []), path.basename(file)]);
      }
    }
  }
  return heights;
}

describe("the stacking ladder", () => {
  it("is declared, as integer literals, ascending from the floor", async () => {
    const rungs = await ladder();

    expect(rungs.length).toBeGreaterThan(0);
    for (const rung of rungs) {
      expect(Number.isInteger(rung.value)).toBe(true);
    }
    expect(rungs.map((rung) => rung.value)).toStrictEqual(
      [...rungs.map((rung) => rung.value)].sort((left, right) => left - right),
    );
  });

  it("names every height any kit sheet spends, and no height none does", async () => {
    const rungs = await ladder();
    const heights = await sheetHeights();

    const unlabelled = [...heights.keys()].filter(
      (height) => !rungs.some((rung) => rung.value === height),
    );
    expect(unlabelled).toEqual([]);

    const unspent = rungs.filter((rung) => !heights.has(rung.value));
    expect(unspent).toEqual([]);
  });
});
