/* Reading the kit's component sources in a test.
 *
 * A stylesheet says what a class does; only the components say whether anything uses it. Several claims in
 * this layer are about that pairing, and a check that reads the stylesheet alone cannot make one: a rule
 * whose selector nothing names, or a mark no component draws, satisfies every assertion the file can make
 * about itself.
 *
 * Test files are excluded. A test naming a class to assert its rule is not a component drawing with it, so
 * counting them as consumers would let a dead rule survive on the strength of the test that reads it. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { primitivesDir } from "./kitStylesheets";

export interface KitSource {
  /** The file name, so a finding names the file a reader will open. */
  readonly name: string;
  readonly source: string;
}

export async function kitComponentSources(): Promise<KitSource[]> {
  const entries = await readdir(primitivesDir);
  const names = entries
    .filter((entry) => entry.endsWith(".tsx") && !entry.includes(".test."))
    .toSorted();
  return Promise.all(
    names.map(async (name) => ({
      name,
      source: await readFile(path.join(primitivesDir, name), "utf8"),
    })),
  );
}

/** The component files naming a class, by file name. */
export async function componentsNaming(className: string): Promise<string[]> {
  const wholeWord = new RegExp(`(?<![\\w-])${className}(?![\\w-])`);
  return (await kitComponentSources())
    .filter((file) => wholeWord.test(file.source))
    .map((file) => file.name);
}
