/* THE COMPONENTS THIS KIT DOES NOT HAVE, ASSERTED OVER WHAT IT EXPORTS.
 *
 * `Skeleton`, `Spinner` and `ProgressBar` are not absent by accident and their absence is not a matter of taste:
 * motion is zero, `--duration` is 0s, the radius is 0 and the circular allowlist holds four static circles, so the
 * usual spinner cannot be drawn in this language at all. Progress that must be shown is a count that changes.
 * `Tooltip`, `Toast`, `Popover` and `LineChart` are absent for reasons of their own, each recorded in the kit's
 * barrels: no value in this product is reachable only by hovering, a floating transient would be a volume with no
 * position, nothing in the seven screens needs a popover, and twelve cobalt lines separated only by dash pattern
 * is unreadable.
 *
 * TWO RULES, AND THE SECOND IS THE ONE THAT CANNOT ROT. The named absences are a list, and a list is a second copy
 * of a fact -- but a NEGATIVE list fails only in the safe direction: a name added to a barrel reddens here, and a
 * name this list has never heard of is caught by the rule below it, which refuses any export whose name is drawn
 * from the vocabulary of motion. `LoadingSpinner`, `ShimmerRow` and `ProgressMeter` are all refused without being
 * named.
 *
 * THE SETS COME FROM THE BARRELS, not from a directory walk, because what a consumer can reach is what a barrel
 * exports: a file present and unexported is not a component this kit has. */

import { describe, expect, it } from "vitest";

import * as domain from "./domain";
import * as layout from "./layout";
import * as primitives from "./primitives";
import { componentNamesIn } from "../testing/kitExports";

/** Every component a consumer can reach, across the three layers. */
const EXPORTED: readonly string[] = [
  ...componentNamesIn(primitives),
  ...componentNamesIn(layout),
  ...componentNamesIn(domain),
];

/** The components section 14 records as not built, each with the reason it is not. */
const NOT_BUILT: readonly string[] = [
  "Skeleton",
  "Spinner",
  "ProgressBar",
  "Tooltip",
  "Toast",
  "Popover",
  "LineChart",
];

/* The vocabulary of motion and of deferred content, in the spellings something might reach for. A component named
 * from it would be a moving surface or a placeholder for one, and this product has neither. */
const MOTION = /spinner|skeleton|shimmer|pulse|loader|loading|progress|throbber|marquee|carousel/i;

describe("the kit's export surface", () => {
  it("exports the components the screens are built from, so the rules below judge a real set", () => {
    expect(EXPORTED.length).toBeGreaterThan(40);
    expect(EXPORTED).toContain("Button");
    expect(EXPORTED).toContain("WeekGrid");
    expect(EXPORTED).toContain("NoticeStrip");
  });

  it.each(NOT_BUILT)("does not export %s, which section 14 records as not built", (name) => {
    expect(EXPORTED).not.toContain(name);
  });

  it("exports nothing named from the vocabulary of motion, whatever it is called", () => {
    expect(EXPORTED.filter((name) => MOTION.test(name))).toEqual([]);
  });

  /* THE MOTION RULE'S OWN CONTROL. An empty result is the passing answer above, and an empty result is also what a
   * pattern that had stopped matching would give. */
  it.each(["Spinner", "LoadingSpinner", "SkeletonRow", "ProgressMeter", "ShimmerCell"])(
    "would refuse an export named %s",
    (name) => {
      expect(MOTION.test(name)).toBe(true);
    },
  );

  it("permits the two bounded readouts that are not motion, which are drawn and not animated", () => {
    /* `MaturityMeter` is block characters because the scale is bounded 0 to 100%, and `DataBar` is a single fill
     * because the magnitude is arbitrary. Neither moves, and neither is named from the vocabulary above. */
    expect(EXPORTED).toContain("MaturityMeter");
    expect(EXPORTED).toContain("DataBar");
    expect(MOTION.test("MaturityMeter")).toBe(false);
    expect(MOTION.test("DataBar")).toBe(false);
  });
});
