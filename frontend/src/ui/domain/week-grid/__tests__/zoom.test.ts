/* THE ZOOM CLAMP, AGAINST THE THREE DISPLAYS THE DESIGN RECORD MEASURED.
 *
 * The clamp is the one figure in the geometry that was settled by a ledger rather than derived from a rule, so the
 * three rows are the test: a 13 inch display caps at 16 hours, a 16 inch at 22, and a 27 inch at the full 24. A
 * formula that produced 15, 21 and 24 would satisfy every other property here and still be wrong. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { srcDir } from "../../../../testing/compileTheme";
import { blankJsComments } from "../../../../../scripts/lib/comments.ts";

import { ZOOM_MAX_HOURS, ZOOM_MIN_HOURS } from "../metrics";
import { MODAL_DURATION_MINUTES, clampVisibleHours, zoomCap, zoomLevels } from "../zoom";

/** The three display rows of the design record, with the grid height each yields. */
const DISPLAYS = [
  { label: "13 inch, 1440x900", gridHeightPx: 626, cap: 16 },
  { label: "16 inch, 1728x1117", gridHeightPx: 836, cap: 22 },
  { label: "27 inch, 2560x1440", gridHeightPx: 1136, cap: 24 },
] as const;

describe("the cap the modal block puts on the range", () => {
  it.each(DISPLAYS)("caps a $label display at $cap hours", ({ gridHeightPx, cap }) => {
    expect(zoomCap(gridHeightPx)).toBe(cap);
  });

  it("is computed from the MODAL thirty minutes, not from the shortest fifteen", () => {
    /* Clamping on fifteen minutes would halve the range on the reference display: the same arithmetic against a
     * fifteen-minute block yields 8 where the modal duration yields 16. */
    const modal = zoomCap(626);
    const shortest = Math.floor((626 * 15) / (19 * 60));

    expect(modal).toBe(16);
    expect(shortest).toBe(8);
  });

  it("never offers less than the floor, even on a display too short for the modal block", () => {
    expect(zoomCap(100)).toBe(ZOOM_MIN_HOURS);
  });

  it("never offers more than the ceiling, however tall the display", () => {
    expect(zoomCap(4000)).toBe(ZOOM_MAX_HOURS);
  });

  it("keeps a thirty-minute block at or above the label floor at its own cap", () => {
    for (const { gridHeightPx, cap } of DISPLAYS) {
      const heightPx = (gridHeightPx / (cap * 60)) * MODAL_DURATION_MINUTES;

      expect(heightPx).toBeGreaterThanOrEqual(19);
    }
  });

  it("would put a thirty-minute block BELOW the floor one level past the cap", () => {
    for (const { gridHeightPx, cap } of DISPLAYS.filter((row) => row.cap < ZOOM_MAX_HOURS)) {
      const heightPx = (gridHeightPx / ((cap + 1) * 60)) * MODAL_DURATION_MINUTES;

      expect(heightPx).toBeLessThan(19);
    }
  });
});

describe("the levels the range offers", () => {
  it("offers the whole range at every display size, so the reader sees how deep it goes", () => {
    const levels = zoomLevels(626);

    expect(levels.map((level) => level.hours)).toEqual(
      Array.from({ length: ZOOM_MAX_HOURS - ZOOM_MIN_HOURS + 1 }, (_, i) => ZOOM_MIN_HOURS + i),
    );
  });

  it("marks a level past the cap UNAVAILABLE WITH A REASON rather than hiding it", () => {
    const levels = zoomLevels(626);
    const beyond = levels.filter((level) => !level.isAvailable);

    expect(beyond.map((level) => level.hours)).toEqual([17, 18, 19, 20, 21, 22, 23, 24]);
    for (const level of beyond) expect(level.unavailableReason).not.toBeNull();
  });

  it("states no reason for a level it offers, so a reason means exactly one thing", () => {
    for (const level of zoomLevels(1136)) {
      expect(level.isAvailable).toBe(true);
      expect(level.unavailableReason).toBeNull();
    }
  });

  it("names the thirty-minute block in the reason, which is what the clamp protects", () => {
    const beyond = zoomLevels(626).find((level) => !level.isAvailable);

    expect(beyond?.unavailableReason).toContain(String(MODAL_DURATION_MINUTES));
  });
});

describe("the setting brought inside the range", () => {
  it("leaves a setting the display can offer alone", () => {
    expect(clampVisibleHours(12, 626)).toBe(12);
  });

  it("brings a setting past the cap down to it, rather than refusing to render", () => {
    expect(clampVisibleHours(24, 626)).toBe(16);
  });

  it("brings a setting below the floor up to it", () => {
    expect(clampVisibleHours(2, 626)).toBe(ZOOM_MIN_HOURS);
  });

  it("keeps a wide display's own deeper setting, which is what the per-display cap is for", () => {
    expect(clampVisibleHours(22, 836)).toBe(22);
    expect(clampVisibleHours(22, 626)).toBe(16);
  });
});

/* THE ARITHMETIC IS STATED ONCE, AND BOTH SCREENS READ IT.
 *
 * It was stated twice for a while: this module and `routes/settings/geometry.ts` each computed the cap, each held its
 * own `zoomLevels` and its own `ZoomLevel` shape, and the two answered differently at one point because Settings
 * derived the height from the window while the Week screen used the reference constant. Settings offered 22 on a 16
 * inch display where the Week screen drew 16, which is exactly what offering a level as unavailable with a stated
 * reason exists to prevent.
 *
 * Settings now reads this module. What that leaves it is the one thing it genuinely owns and this module cannot know:
 * the height a grid would get in a window it has no grid to measure. The assertions below are what stop a second copy
 * reappearing, in either direction. */
describe("one statement of the clamp", () => {
  const sourceDir = path.join(srcDir, "..", "src");

  async function sources(): Promise<{ name: string; text: string }[]> {
    const entries = await readdir(sourceDir, { withFileTypes: true, recursive: true });
    const files = entries
      .filter(
        (entry) => entry.isFile() && /\.tsx?$/.test(entry.name) && !entry.name.includes(".test."),
      )
      .map((entry) => path.join(entry.parentPath, entry.name));
    return Promise.all(
      files.map(async (file) => ({
        name: path.relative(sourceDir, file),
        text: await readFile(file, "utf8"),
      })),
    );
  }

  it("declares the cap, the levels and the clamp in exactly one file", async () => {
    const files = await sources();
    const here = path.join("ui", "domain", "week-grid", "zoom.ts");

    for (const name of ["zoomCap", "zoomLevels", "clampVisibleHours"]) {
      const declaring = files
        .filter((file) => file.text.includes(`export function ${name}`))
        .map((file) => file.name);

      expect(declaring, `${name} is declared more than once`).toEqual([here]);
    }
  });

  it("is what every consumer imports, rather than a formula of its own", async () => {
    const consumers = (await sources()).filter((file) =>
      /\bzoomCap\(|\bzoomLevels\(|\bclampVisibleHours\(/.test(file.text),
    );

    expect(consumers.length).toBeGreaterThan(1);
    for (const file of consumers) {
      if (file.name === path.join("ui", "domain", "week-grid", "zoom.ts")) continue;
      /* A sibling inside the family imports it as `./zoom`; anything outside names the family. Both are reading
       * this module rather than restating it, which is the whole of the claim. */
      expect(file.text, `${file.name} states the cap rather than reading it`).toMatch(
        /from "(\.\/zoom|[^"]*week-grid\/zoom)"/,
      );
    }
  });

  it("holds the modal duration in one constant, not two", async () => {
    const declaring = (await sources())
      .filter((file) => /MODAL_[A-Z_]*MINUTES =/.test(file.text))
      .map((file) => file.name);

    expect(declaring).toEqual([path.join("ui", "domain", "week-grid", "zoom.ts")]);
  });

  /* AND A COPY UNDER ANY OTHER NAME. The three assertions above match on the exported NAMES, which catches a rename by
   * substring only by luck: an inline `Math.floor((height * 30) / (19 * 60))` under a name of its own passed all of
   * them. The formula has a shape, so the shape is what is searched for: a floor over a product of the protected
   * duration and a quotient of the label floor, in whichever spelling. */
  it("is not restated under a name of its own, in any spelling of the formula", async () => {
    /* The floor's argument is a quotient whose numerator names the protected duration and whose denominator names the
     * label floor. Matched across newlines, because the one true statement of it is wrapped over two lines. */
    const shape =
      /Math\.floor\s*\(\s*\(?[^;]*?(MODAL_DURATION_MINUTES|\b30\b)[^;]*?\/[^;]*?(BLOCK_H_LABEL_PX|\b19\b)/s;
    const restating = (await sources())
      .filter((file) => shape.test(file.text))
      .map((file) => file.name);

    expect(restating).toEqual([path.join("ui", "domain", "week-grid", "zoom.ts")]);
  });

  it("is read by BOTH screens, so neither can answer the question alone", async () => {
    const reading = (await sources())
      .filter((file) => /from "(\.\/zoom|[^"]*week-grid\/zoom)"/.test(file.text))
      .map((file) => file.name);

    expect(reading).toContain(path.join("routes", "settings", "geometry.ts"));
    expect(reading).toContain(path.join("routes", "settings", "components", "GeometryPanel.tsx"));
    expect(reading).toContain(path.join("ui", "domain", "week-grid", "WeekGrid.tsx"));
  });

  /* AND THE CLAMP IS CALLED ONCE, which is a stronger claim than the four above and a different one. Importing this
   * module rather than restating its formula satisfies every one of them and still yields TWO figures: a surface that
   * clamps the level it holds agrees with the grid on the reference display and disagrees on every other, because the
   * grid answers from a measurement and a second caller has none to answer from. One call site is what makes the
   * reading and the drawing the same figure rather than two that usually match.
   *
   * Counted per occurrence rather than per file, so a second call beside the first is caught too, and comments are
   * blanked first because prose naming the function is not a caller. */
  it("is called from exactly one place, so a reading and a drawing cannot be two figures", async () => {
    const here = path.join("ui", "domain", "week-grid", "zoom.ts");
    const callSites = (await sources()).flatMap((file) => {
      if (file.name === here) return [];
      const calls = blankJsComments(file.text).match(/\bclampVisibleHours\(/g) ?? [];
      return calls.map(() => file.name);
    });

    expect(callSites).toEqual([path.join("ui", "domain", "week-grid", "WeekGrid.tsx")]);
  });
});
