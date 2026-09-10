/* THE STACKING LADDER, READ FROM THE TOKEN LAYER AND CROSSED AGAINST THE SHEETS.
 *
 * A stacking order spread across seven component sheets is an order nobody can read: each sheet
 * states one number, and the ordering lives nowhere until a reader reconstructs it. So the ladder
 * is declared once in `src/tokens/layout.css`, and this file holds it to two claims: the rungs
 * ascend, and every stacking sheet reads one. A rung renamed without its sheet, or a sheet
 * regaining a raw number, breaks the crossing in one direction or the other.
 *
 * The heights are read from the stylesheets rather than restated here, for the same reason
 * `src/ui/primitives/__tests__/overlayLayers.test.ts` reads them: a copy of the numbers in the
 * test is a third place for the order to disagree with itself. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { codeWithoutComments, scanCss } from "../../scripts/lib/css-scan.ts";
import { srcDir } from "../testing/compileTheme";
import { domainDir, primitivesDir } from "../testing/kitStylesheets";

/** Every `--z-*` rung the token layer declares, in file order. */
async function ladder(): Promise<{ name: string; value: number }[]> {
  const source = await readFile(path.join(srcDir, "tokens", "layout.css"), "utf8");
  return scanCss(source)
    .declarations.filter((declaration) => declaration.name.startsWith("--z-"))
    .map((declaration) => ({ name: declaration.name, value: Number(declaration.value) }));
}

const STACKING_SHEETS = [
  path.join(primitivesDir, "overlay.css"),
  path.join(primitivesDir, "Select.css"),
  path.join(primitivesDir, "DatePicker.css"),
  path.join(primitivesDir, "states.css"),
  path.join(domainDir, "week-grid", "grid.css"),
  path.join(domainDir, "week-grid", "band.css"),
  path.join(domainDir, "week-grid", "block.css"),
];

interface ZIndexDeclaration {
  readonly sheet: string;
  readonly value: string;
}

const zIndexToken = (value: string): string | null =>
  /^var\((--z-\w+(?:-\w+)*)\)$/.exec(value)?.[1] ?? null;

/** Every `z-index` declaration the stacking sheets make, with prose excluded. */
async function zIndexDeclarations(): Promise<ZIndexDeclaration[]> {
  const sources = await Promise.all(
    STACKING_SHEETS.map(async (file) => ({
      sheet: path.basename(file),
      source: codeWithoutComments(await readFile(file, "utf8")),
    })),
  );
  const declarations: ZIndexDeclaration[] = [];
  for (const { sheet, source } of sources) {
    for (const match of source.matchAll(/z-index\s*:\s*([^;}]+)/g)) {
      declarations.push({ sheet, value: match[1].trim() });
    }
  }
  return declarations;
}

describe("the stacking ladder", () => {
  it("is declared, as integer literals, ascending from the floor", async () => {
    const rungs = await ladder();

    expect(rungs.length).toBeGreaterThan(0);
    for (const rung of rungs) {
      expect(Number.isInteger(rung.value)).toBe(true);
    }
    const values = rungs.map((rung) => rung.value);
    expect(values).toStrictEqual(values.toSorted((left, right) => left - right));
  });

  it("declares no literal z-index and consumes every rung", async () => {
    const [rungs, declarations] = await Promise.all([ladder(), zIndexDeclarations()]);
    const invalid = declarations.filter(({ value }) => zIndexToken(value) === null);
    const referenced = declarations.flatMap(({ value }) => {
      const token = zIndexToken(value);
      return token === null ? [] : [token];
    });

    expect(declarations).toHaveLength(12);
    expect(invalid).toEqual([]);
    expect(referenced.filter((token) => !rungs.some((rung) => rung.name === token))).toEqual([]);
    expect([...new Set(referenced)].toSorted()).toEqual(rungs.map((rung) => rung.name).toSorted());
  });
});
