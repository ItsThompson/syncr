/* Reading the kit's own stylesheets in a test.
 *
 * A component's stylesheet is the authority on its channels, so a test that wants to know what a state does
 * reads the file the browser loads rather than a copy of it in the test. */

import { readFile } from "node:fs/promises";
import path from "node:path";

import { srcDir } from "./compileTheme";

export const primitivesDir = path.join(srcDir, "ui", "primitives");

/** One of the kit's stylesheets, by file name. */
export function kitStylesheet(name: string): Promise<string> {
  return readFile(path.join(primitivesDir, name), "utf8");
}

/** Several of the kit's stylesheets, concatenated in the order given, as one cascade. */
export async function kitStylesheets(...names: readonly string[]): Promise<string> {
  const sheets = await Promise.all(names.map((name) => kitStylesheet(name)));
  return sheets.join("\n");
}
