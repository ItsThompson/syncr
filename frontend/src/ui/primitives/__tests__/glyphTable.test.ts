/* THE GLYPH TABLE, AND THE UNIQUENESS THE TESTING STRATEGY ASKS FOR BY NAME.
 *
 * "Assert every glyph in the kit's glyph table is unique" exists because the origin marks, the pinned mark,
 * the proposal-source mark and the overlap count must not collide, even where they appear at different tiers
 * and can never co-render. A table makes that checkable; per-component literals do not.
 *
 * The marks are written as codepoints, so these tests also pin the codepoint rather than a lookalike: the
 * indeterminate mark and the disclosure minus are U+2212 MINUS SIGN and not a hyphen, which is a distinction
 * a literal in a component would hide. */

import { describe, expect, it } from "vitest";

import { kitStylesheet } from "../../../testing/kitStylesheets";

const GLYPH_DECLARATION = /--glyph-([a-z-]+):\s*("(?:[^"\\]|\\.)*")/g;

async function glyphTable(): Promise<Map<string, string>> {
  const css = await kitStylesheet("glyphs.css");
  const table = new Map<string, string>();
  for (const match of css.matchAll(GLYPH_DECLARATION)) table.set(match[1], match[2]);
  return table;
}

describe("the glyph table", () => {
  it("holds every mark the kit draws", async () => {
    const table = await glyphTable();

    expect([...table.keys()].toSorted()).toEqual([
      "bracket-close",
      "bracket-open",
      "check",
      "dismiss",
      "minus",
      "month-next",
      "month-previous",
      "plus",
      "select-arrow",
    ]);
  });

  it("holds no mark no component draws, because a table is built to demand like everything else", async () => {
    const css = await kitStylesheet("glyphs.css");

    for (const mark of (await glyphTable()).keys()) {
      expect(css).toContain(`var(--glyph-${mark})`);
    }
  });

  it("gives every meaning its own mark, so two marks cannot collide", async () => {
    const values = [...(await glyphTable()).values()];

    expect(new Set(values).size).toBe(values.length);
  });

  it("writes each mark as a codepoint, so a lookalike cannot be substituted", async () => {
    const table = await glyphTable();

    expect(table.get("minus")).toBe('"\\2212"');
    expect(table.get("check")).toBe('"\\2713"');
    expect(table.get("dismiss")).toBe('"\\2715"');
    expect(table.get("select-arrow")).toBe('"\\25BE"');
  });

  it("draws the disclosure minus with the minus sign rather than a hyphen", async () => {
    const table = await glyphTable();

    expect(table.get("minus")).not.toContain("-");
  });

  it("states the bracketed form once, so a key hint and a disclosure cannot differ", async () => {
    const css = await kitStylesheet("glyphs.css");
    const bracketed = /\.glyph--bracketed::before\s*\{([^}]*)\}/.exec(css);

    expect(bracketed?.[1]).toContain("var(--glyph-bracket-open)");
    expect(bracketed?.[1]).toContain("var(--glyph-bracket-close)");
  });

  /* One slot is named for its meaning rather than its mark, and it is the only one that can be: disclosure
   * carries two marks and switches between them on the trigger's own state. */
  it("names every slot after its mark rather than after a meaning", async () => {
    const css = await kitStylesheet("glyphs.css");
    const slots = [
      ...css.matchAll(/\.glyph--([a-z-]+)\s*\{\s*--glyph:\s*var\(--glyph-([a-z-]+)\)/g),
    ].filter(([, slot]) => slot !== "disclosure");

    expect(slots.length).toBeGreaterThan(3);
    for (const [, slot, mark] of slots) expect(slot).toBe(mark);
  });
});
