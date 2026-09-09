/* THE SIX REFERENCE SHEETS DRAW EACH HATCH IN ITS OWN INK, THROUGH THE PAINTER'S `color`.
 *
 * A token-layer gradient resolves its var()s where it is DECLARED (`:root`), so an element-level
 * `--hatch-ink` write is dead: the ink arrives through `color` on the element that paints. Text inside a
 * painter re-declares its own color when it must remain legible. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { designSheetDir } from "../../../../../scripts/lib/paths.ts";

interface Painter {
  readonly selector: string;
  readonly ink: RegExp;
}

const areaHatchInk =
  /color:\s*color-mix\(in srgb,\s*var\(--ai\)\s*var\(--hatch-mix\),\s*var\(--paper-raised\)\)/;
const forbiddenHatchInk = /color:\s*var\(--forbidden-hatch-ink\)/;
const frameHatchInk = /color:\s*var\(--rule\)/;

/** Each sheet and the selectors whose rules must carry the hatch ink on `color`. */
const PAINTERS: Readonly<Record<string, readonly Painter[]>> = {
  "specimen.html": [
    { selector: ".ramp .fill", ink: areaHatchInk },
    { selector: ".stack>span", ink: areaHatchInk },
  ],
  "components.html": [
    { selector: ".legend .sw", ink: areaHatchInk },
    { selector: ".pie .w", ink: areaHatchInk },
    { selector: ".sbar>span", ink: areaHatchInk },
  ],
  "screens.html": [{ selector: ".stack>span", ink: areaHatchInk }],
  "decisions.html": [{ selector: "[data-framefill=hatch] .blk.frame", ink: frameHatchInk }],
  "scratch/block-states.html": [
    { selector: ".ramp .fill", ink: areaHatchInk },
    { selector: ".forbid", ink: forbiddenHatchInk },
  ],
  "scratch/week-density.html": [{ selector: ".forbid", ink: forbiddenHatchInk }],
};

const escapeRegExp = (selector: string): string => selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Every sheet read once up front, so no test awaits inside a loop. A missing sheet fails module load,
 *   which reports as a collection error naming the path; there is nothing a per-test assert adds. */
const TEXTS = new Map(
  await Promise.all(
    Object.keys(PAINTERS).map(async (sheet) => {
      return [sheet, await readFile(path.join(designSheetDir, sheet), "utf8")] as const;
    }),
  ),
);

describe("the reference sheets draw each hatch through the painter's own color", () => {
  for (const [sheet, painters] of Object.entries(PAINTERS)) {
    const text = TEXTS.get(sheet) ?? "";

    it(`${sheet} carries no element-level --hatch-ink write`, () => {
      /* Comments are stripped first: the sheets explain the substitution mechanism in prose, and a
         sentence like "an --hatch-ink: write is dead" must not read as an offense. */
      const css = text.replace(/\/\*[\s\S]*?\*\//g, "");
      expect(css.match(/--hatch-ink\s*:/g) ?? []).toEqual([]);
    });

    for (const painter of painters) {
      it(`${sheet}: ${painter.selector} spends color on the hatch ink`, () => {
        const rule = new RegExp(`${escapeRegExp(painter.selector)}\\s*\\{([^}]*)\\}`).exec(text);
        expect(rule, `${sheet} no longer styles ${painter.selector}`).not.toBeNull();
        expect(rule?.[1]).toMatch(painter.ink);
      });
    }
  }

  it("keeps text inside forbidden bands off the hatch channel", () => {
    for (const sheet of [
      "components.html",
      "screens.html",
      "scratch/block-states.html",
      "scratch/week-density.html",
    ]) {
      const span = /\.forbid\s+span\s*\{([^}]*)\}/.exec(TEXTS.get(sheet) ?? "");
      expect(span, `${sheet} no longer styles .forbid span`).not.toBeNull();
      expect(span?.[1]).toMatch(/color:\s*var\(--text-muted\)/);
    }
  });

  it("keeps frame labels off the hatch channel", () => {
    const frameLabel = /\[data-framefill=hatch\]\s+\.blk\.frame\s+\.t\s*\{([^}]*)\}/.exec(
      TEXTS.get("decisions.html") ?? "",
    );
    expect(frameLabel, "decisions.html no longer styles hatched frame labels").not.toBeNull();
    expect(frameLabel?.[1]).toMatch(/color:\s*var\(--ink-soft\)/);
  });
});
