/* Reading component sources in a test.
 *
 * A stylesheet says what a class does; only the components say whether anything uses it. Several claims in
 * the kit are about that pairing, and a check that reads the stylesheet alone cannot make one: a rule whose
 * selector nothing names, or a mark no component draws, satisfies every assertion the file can make about
 * itself.
 *
 * Test files are excluded. A test naming a class to assert its rule is not a component drawing with it, so
 * counting them as consumers would let a dead rule survive on the strength of the test that reads it. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { srcDir } from "./compileTheme";
import { primitivesDir } from "./kitStylesheets";

export interface ComponentSource {
  /** The path relative to the root read, so a finding names the file a reader will open. */
  readonly name: string;
  readonly source: string;
}

/** Every component under a root, the kit's own layer by default. */
export async function componentSources(root: string = primitivesDir): Promise<ComponentSource[]> {
  const entries = await readdir(root, { withFileTypes: true, recursive: true });
  const files = entries
    .filter((entry) => entry.isFile())
    .filter((entry) => entry.name.endsWith(".tsx") && !entry.name.includes(".test."))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .toSorted();
  return Promise.all(
    files.map(async (file) => ({
      name: path.relative(root, file),
      source: await readFile(file, "utf8"),
    })),
  );
}

/** The components naming a class, by path relative to the root read. */
export async function componentsNaming(
  className: string,
  root: string = primitivesDir,
): Promise<string[]> {
  const wholeWord = new RegExp(`(?<![\\w-])${className}(?![\\w-])`);
  return (await componentSources(root))
    .filter((file) => wholeWord.test(file.source))
    .map((file) => file.name);
}

/** Everything the application renders, which is who a kit class has to be named by to be alive. */
export const appSourceRoot = srcDir;
