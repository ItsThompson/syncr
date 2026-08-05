/* WHO NAMES A CLASS, read from the class lists a component writes rather than from its text.
 *
 * A stylesheet says what a class does; only the components say whether anything uses it. Several claims in
 * the kit are about that pairing, and a check that reads the stylesheet alone cannot make one: a rule whose
 * selector nothing names, or a mark no component draws, satisfies every assertion the file can make about
 * itself.
 *
 * A CLASS NAME IN PROSE IS NOT A CONSUMER, and reading the raw file made it one. A sentence in a comment
 * mentioning `.calendar__ghost` kept a dead rule alive, and the word "overlay" in a comment made a component
 * that draws no overlay one of the surfaces carrying the shadow: a false negative in the check written to
 * find dead rules, and a false positive that fails with a mysterious message. It is the same defect as the
 * one word of prose that compiled `backdrop-filter` into the stylesheet, which is why `blankJsComments`
 * exists and why three other checks call it before matching anything.
 *
 * So comments are blanked and then the CLASS LISTS are extracted: a `className` attribute or a class
 * composer's argument, which is everything that reaches an element. That also settles the weaker version of
 * the same problem, a class name inside an unrelated string literal.
 *
 * Test files and fixtures are excluded. A test naming a class to assert its rule is not a component drawing
 * with it, so counting them as consumers would let a dead rule survive on the strength of the test that
 * reads it.
 *
 * BOTH `.ts` AND `.tsx` ARE READ. A class list legitimately lives in a `.ts` module: a variant map shared by
 * three components is not a component itself, and reading only `.tsx` would have called every class in it dead. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { classStringsIn } from "../../scripts/lib/class-strings.ts";
import { blankJsComments } from "../../scripts/lib/comments.ts";
import { srcDir } from "./compileTheme";
import { primitivesDir } from "./kitStylesheets";

const EXCLUDED_DIRECTORY = "__fixtures__";

/* THE TREE IS READ ONCE PER ROOT, because the questions asked of it are asked per CLASS. Two layers ask "is this
 * class named by anything the application renders" for every class they declare, which is roughly two hundred
 * questions over roughly four hundred files: re-reading the tree per question is eighty thousand file reads, and it
 * took the two layer-rule suites past the runner's own timeout as the application grew. The answer is the same for
 * every question, so it is computed once. A test only ever reads.
 *
 * NEVER INVALIDATED, which is correct for a run-once process and is the one thing to know about it: under
 * `vitest --watch` a source file changed mid-session is answered from the cache until the process restarts. */
const BY_ROOT = new Map<string, Promise<ComponentSource[]>>();

export interface ComponentSource {
  /** The path relative to the root read, so a finding names the file a reader will open. */
  readonly name: string;
  /** Every class list the file writes, which is what will reach an element. */
  readonly classLists: readonly string[];
}

/** Matches a class as a whole word, so `state-row` is not found inside `state-rows`. */
function matcherFor(className: string): RegExp {
  return new RegExp(`(?<![\\w-])${className}(?![\\w-])`);
}

/** Every class list a source writes, with comments blanked first. */
export function classListsIn(source: string): string[] {
  return classStringsIn(blankJsComments(source)).map((found) => found.text);
}

/** True when a source draws with a class, rather than mentioning it. */
export function namesClass(source: string, className: string): boolean {
  const matches = matcherFor(className);
  return classListsIn(source).some((classList) => matches.test(classList));
}

/** Every component under a root, the kit's own layer by default. */
export function componentSources(root: string = primitivesDir): Promise<ComponentSource[]> {
  const held = BY_ROOT.get(root);
  if (held !== undefined) return held;
  const reading = readComponentSources(root);
  BY_ROOT.set(root, reading);
  return reading;
}

async function readComponentSources(root: string): Promise<ComponentSource[]> {
  const entries = await readdir(root, { withFileTypes: true, recursive: true });
  const files = entries
    .filter((entry) => entry.isFile())
    .filter((entry) => /\.tsx?$/.test(entry.name) && !entry.name.includes(".test."))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .filter((file) => !path.relative(root, file).split(path.sep).includes(EXCLUDED_DIRECTORY))
    .toSorted();
  return Promise.all(
    files.map(async (file) => ({
      name: path.relative(root, file),
      classLists: classListsIn(await readFile(file, "utf8")),
    })),
  );
}

/** The components naming a class, by path relative to the root read. */
export async function componentsNaming(
  className: string,
  root: string = primitivesDir,
): Promise<string[]> {
  const matches = matcherFor(className);
  return (await componentSources(root))
    .filter((file) => file.classLists.some((classList) => matches.test(classList)))
    .map((file) => file.name);
}

/** Everything the application renders, which is who a kit class has to be named by to be alive. */
export const appSourceRoot = srcDir;
