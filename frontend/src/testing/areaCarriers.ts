/* WHICH CLASSES CARRY AN AREA'S OWN INK, derived from the components that emit them.
 *
 * A screen that must draw NO Area ink inside some subtree needs to know what Area ink looks like as a class, and
 * three guards written against a hand-kept list of those classes have each had a hole. The Areas screen's cobalt
 * guard, the instrument for the strictest chart rule in the system, had three: it walked the figure rather than the
 * panel, then its five-string list omitted `chart-ink` (the class every painted element carries), then its prefix set
 * omitted the `week-block--area-NN` family entirely and a real kit `Block` inside a deviation panel passed 2375
 * tests. Each hole was found by somebody else, and each fix was a longer list.
 *
 * SO THE LIST IS DERIVED FROM ITS EMITTERS RATHER THAN WRITTEN DOWN. Every component that paints a category does it
 * through one `cva` call whose variants are keyed by the ramp step, so the set of carrier classes IS the set of
 * values in those maps, plus the base each map hangs off. A fourth family cannot be omitted, because a fourth family
 * is a fourth `pigment:` map and this reads every one of them.
 *
 * THE DERIVATION IS CHECKED BY A FLOOR, because a broken extractor would otherwise pass everything. Callers assert
 * that the three families known to exist are among what was derived, so a regex that stops matching goes red rather
 * than silently returning nothing.
 *
 * `area-name` IS ADDED RATHER THAN DERIVED, and it is the one exception. It is the chip's own container and nothing
 * paints it, so no pigment map can produce it; it is here because a row carrying the chip's wrapper is a row carrying
 * an Area's identity whether or not the ink reached it. That is stated rather than hidden, and it is the only entry
 * a reader has to take on trust. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { blankJsComments } from "../../scripts/lib/comments.ts";
import { srcDir } from "./compileTheme";

const kitDir = path.join(srcDir, "ui");

/** The chip's container, which no pigment map emits. See the module note. */
export const CHIP_CONTAINER_CLASS = "area-name";

/** The families that exist today, which every caller asserts are among what was derived. */
export const KNOWN_AREA_INK_FAMILIES = ["chart-ink", "area-chip", "week-block"] as const;

/* A `cva` base is its first argument, a bare string. A variant map keyed by the ramp's steps is what makes a call an
 * Area-ink emitter, so the base is only collected for a source that has one. */
const CVA_BASE = /\bcva\(\s*"([\w-]+)"/g;
/* A variant map keyed by a two-digit ramp step or the vacancy, which is what `ChartPigment` and `AreaPigment` are.
 * Read to the closing brace of the map, which is the first `}` at the same nesting: no value in these maps is an
 * object, which is what makes the non-greedy match safe here rather than merely convenient. */
const PIGMENT_MAP = /\bpigment:\s*\{([^{}]*)\}/g;
/* Every other variant map in the same call, so a texture keyed by a hatch name comes along with the ink it belongs
 * to: `chart-hatch--fwd` is derived from the pigment and is as much an Area's own channel as the ink is. */
const VARIANT_MAP = /\b[\w-]+:\s*\{([^{}]*)\}/g;
const QUOTED_CLASS = /"([\w-]+)"/g;

function classesIn(block: string): string[] {
  return [...block.matchAll(QUOTED_CLASS)].map((found) => found[1]);
}

/**
 * Every class a kit component paints an Area's ink with, and the two channels beside it.
 *
 * Comments are blanked first, for the reason `kitSources` blanks them: a class name in prose is not a class anything
 * emits, and one paragraph naming `chart-ink--01` would otherwise be indistinguishable from a map producing it.
 */
export async function areaInkClasses(): Promise<readonly string[]> {
  const entries = await readdir(kitDir, { withFileTypes: true, recursive: true });
  const files = entries
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name))
    .filter((entry) => !entry.name.includes(".test."))
    .map((entry) => path.join(entry.parentPath, entry.name));

  const sources = await Promise.all(files.map((file) => readFile(file, "utf8")));
  const found = new Set<string>([CHIP_CONTAINER_CLASS]);
  for (const raw of sources) {
    const source = blankJsComments(raw);
    PIGMENT_MAP.lastIndex = 0;
    if (!PIGMENT_MAP.test(source)) continue;
    for (const [, base] of source.matchAll(CVA_BASE)) found.add(base);
    for (const [, block] of source.matchAll(VARIANT_MAP)) {
      for (const painted of classesIn(block)) found.add(painted);
    }
  }
  return [...found].toSorted();
}

/**
 * A matcher for every class carrying an Area's ink, derived, with the families it is built over.
 *
 * The classes are matched as whole words or as a prefix of a hyphenated variant, so `chart-ink` finds
 * `chart-ink--01` and `week-block` finds `week-block--area-01`, and neither finds a longer unrelated word.
 */
export async function areaInkMatcher(): Promise<{
  readonly matches: (className: string) => boolean;
  readonly derived: readonly string[];
}> {
  const derived = await areaInkClasses();
  const patterns = derived.map((painted) => new RegExp(`^${painted}(--|$)`));
  return { derived, matches: (className) => patterns.some((one) => one.test(className)) };
}
