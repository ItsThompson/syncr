/* Reading the keystrokes the product registers, out of the source that registers them.
 *
 * `useKeyBinding` is the one call a keystroke arrives through, so a check that crosses a claim about the keyboard
 * against the tree reads these calls. Two checks do, and they must not read the population two different ways: the
 * shell crosses its own keyboard map against what is bound, and the week grid crosses the drag's degrees of freedom
 * against the pair the design language calls the drag's equivalent.
 *
 * TWO EXCLUSIONS, BOTH DELIBERATE. Comments are blanked, so a paragraph naming a binding is not read as one. A test
 * file is left out, because a binding a test mounts puts no key on a screen a reader can reach.
 *
 * A SPELLING THIS CANNOT RESOLVE IS REPORTED AS `null` RATHER THAN GUESSED. A caller that knows which constants a
 * binding may name passes them in; a caller that reads `null` decides for itself whether an unreadable key is a
 * pass or a refusal, and both of today's callers refuse it. Reading it as "some other key" is the one answer that
 * could hide a binding. */

import { readFile } from "node:fs/promises";

import { blankJsComments } from "./comments.ts";
import { filesUnder } from "./files.ts";
import { appSourceDir } from "./paths.ts";

const BINDING_CALL = /useKeyBinding\(\s*\{([^}]*)\}/g;

/** One shipped file, with its comments blanked and every offset preserved. */
export interface ShippedSource {
  readonly file: string;
  readonly code: string;
}

/** A `useKeyBinding` call as the source makes it. */
export interface KeyRegistration {
  readonly file: string;
  /** The key this answers to, or null where its spelling could not be resolved. */
  readonly key: string | null;
  readonly options: string;
  readonly withPlatformModifier: boolean;
  readonly withShift: boolean;
}

/** Every `.ts` and `.tsx` file the application ships, comments blanked, tests left out. */
export async function shippedSources(): Promise<ShippedSource[]> {
  const files = (await filesUnder(appSourceDir, [".ts", ".tsx"])).filter(
    (file) => !file.includes(".test."),
  );
  return Promise.all(
    files.map(async (file) => ({ file, code: blankJsComments(await readFile(file, "utf8")) })),
  );
}

/** The registrations one source makes. `namedKeys` resolves a `key:` that names a constant instead of spelling it. */
export function keyRegistrationsIn(
  { file, code }: ShippedSource,
  namedKeys: ReadonlyMap<string, string> = new Map(),
): KeyRegistration[] {
  return [...code.matchAll(BINDING_CALL)].map((match) => ({
    file,
    key: keyOf(match[1], namedKeys),
    options: match[1].trim(),
    withPlatformModifier: /withPlatformModifier:\s*true/.test(match[1]),
    withShift: /withShift:\s*true/.test(match[1]),
  }));
}

/** Every registration the shipped tree makes. */
export async function keyRegistrations(
  namedKeys?: ReadonlyMap<string, string>,
): Promise<KeyRegistration[]> {
  const sources = await shippedSources();
  return sources.flatMap((source) => keyRegistrationsIn(source, namedKeys));
}

function keyOf(options: string, namedKeys: ReadonlyMap<string, string>): string | null {
  const spelt = /key:\s*"([^"]*)"/.exec(options);
  if (spelt !== null) return spelt[1];
  const named = /key:\s*([A-Za-z_$][\w$]*)/.exec(options);
  return named === null ? null : (namedKeys.get(named[1]) ?? null);
}
