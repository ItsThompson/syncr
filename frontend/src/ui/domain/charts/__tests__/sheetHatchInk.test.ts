/* THE THREE SHEETS A REVIEWER READS DRAW EACH HATCH IN ITS OWN INK, THROUGH THE PAINTER'S `color`.
 *
 * A token-layer gradient resolves its var()s where it is DECLARED (`:root`), so an element-level
 * `--hatch-ink` write is dead: the ink arrives through `color` on the element that paints, the same shape
 * `charts.css` gives `.chart-ink`. The legend and swatch rows keep their text ink because only the painter
 * spends `color` on the channel, and `.forbid span` re-declares its own so the band label stays legible. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { designSheetDir } from "../../../../../scripts/lib/paths.ts";

/** Each sheet and the selectors whose rules must carry the hatch ink on `color`. */
const PAINTERS: Readonly<Record<string, readonly string[]>> = {
  "specimen.html": [".ramp .fill", ".stack>span"],
  "components.html": [".legend .sw", ".pie .w", ".sbar>span"],
  "screens.html": [".stack>span"],
};

/** The declaration a painter rule has to spend on the hatch ink. */
const INK =
  /color:\s*color-mix\(in srgb,\s*var\(--ai\)\s*var\(--hatch-mix\),\s*var\(--paper-raised\)\)/;

const escapeRegExp = (selector: string): string => selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Every sheet read once up front, so no test awaits inside a loop. */
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
      expect(TEXTS.has(sheet), `${sheet} disappeared from ${designSheetDir}`).toBe(true);
      expect(text.match(/--hatch-ink\s*:/g) ?? []).toEqual([]);
    });

    for (const selector of painters) {
      it(`${sheet}: ${selector} spends color on the hatch ink`, () => {
        const rule = new RegExp(`${escapeRegExp(selector)}\\s*\\{([^}]*)\\}`).exec(text);
        expect(rule, `${sheet} no longer styles ${selector}`).not.toBeNull();
        expect(rule?.[1]).toMatch(INK);
      });
    }
  }

  it("keeps the forbidden band's label off the hatch channel", () => {
    for (const sheet of ["components.html", "screens.html"]) {
      const span = /\.forbid\s+span\s*\{([^}]*)\}/.exec(TEXTS.get(sheet) ?? "");
      expect(span, `${sheet} no longer styles .forbid span`).not.toBeNull();
      expect(span?.[1]).toMatch(/color:\s*var\(--text-muted\)/);
    }
  });
});
