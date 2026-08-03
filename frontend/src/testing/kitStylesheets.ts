/* Reading the kit's own stylesheets in a test.
 *
 * A component's stylesheet is the authority on its channels, so a test that wants to know what a state does
 * reads the file the browser loads rather than a copy of it in the test.
 *
 * The three layers are read the same way and each asserts its own claims, so the directory is a parameter and
 * the readers are not: a second copy of "which properties survive forced colors" in a second layer's test is
 * how two layers come to disagree about it. `layerRules.ts` holds the readers those claims rest on. */

import { readFile } from "node:fs/promises";
import path from "node:path";

import { srcDir } from "./compileTheme";

export const primitivesDir = path.join(srcDir, "ui", "primitives");
export const layoutDir = path.join(srcDir, "ui", "layout");
export const domainDir = path.join(srcDir, "ui", "domain");

/** One of the kit's stylesheets, by file name, from the layer given. */
export function kitStylesheet(name: string, dir: string = primitivesDir): Promise<string> {
  return readFile(path.join(dir, name), "utf8");
}

/** Several of the kit's stylesheets, concatenated in the order given, as one cascade. */
export async function kitStylesheets(...names: readonly string[]): Promise<string> {
  const sheets = await Promise.all(names.map((name) => kitStylesheet(name)));
  return sheets.join("\n");
}
