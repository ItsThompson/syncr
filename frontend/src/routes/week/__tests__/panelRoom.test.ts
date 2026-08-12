/* THE MIRROR OF --bp-wide, HELD AGAINST THE FENCE IT MIRRORS.
 *
 * The panel's column is fenced to the `wide:` variant and the mirror decides whether the panel opens unasked. Two
 * spellings of one threshold is what this crosses: the assertion reads the COMPILED media query rather than the token,
 * because the compiled query is what the browser evaluates and it is one step further along the chain that
 * `theme.test.ts` already holds against layout.css. */

import { afterEach, describe, expect, it } from "vitest";

import { compileUtilities } from "../../../testing/compileTheme";
import { WIDE_MIN_WIDTH_PX, hasRoomForDetailPanel } from "../panelRoom";

/* Restored after each case rather than inside one, which is the pattern this screen's other suites use: a case that
 * fails mid-way would otherwise leave its width behind for the next one. */
const JSDOM_WIDTH = window.innerWidth;

afterEach(() => {
  window.innerWidth = JSDOM_WIDTH;
});

describe("the width the detail panel needs", () => {
  it("is the threshold the wide: variant compiles to, which is what fences the panel's column", async () => {
    const compiled = await compileUtilities(["wide:block"]);

    expect(compiled).toContain(`@media (width >= ${WIDE_MIN_WIDTH_PX}px)`);
  });

  it("answers from the viewport, at the threshold and either side of it", () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX;
    expect(hasRoomForDetailPanel()).toBe(true);

    window.innerWidth = WIDE_MIN_WIDTH_PX - 1;
    expect(hasRoomForDetailPanel()).toBe(false);

    window.innerWidth = WIDE_MIN_WIDTH_PX + 1;
    expect(hasRoomForDetailPanel()).toBe(true);
  });
});
