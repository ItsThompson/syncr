/* THE GLYPH TABLE, AND THE UNIQUENESS THE TESTING STRATEGY ASKS FOR BY NAME.
 *
 * "Assert every glyph in the kit's glyph table is unique" exists because the origin marks, the pinned mark,
 * the proposal-source mark and the overlap count must not collide, even where they appear at different tiers
 * and can never co-render. A table makes that checkable; per-component literals do not.
 *
 * The marks are written as codepoints, so these tests also pin the codepoint rather than a lookalike: the
 * indeterminate mark and the disclosure minus are U+2212 MINUS SIGN and not a hyphen, which is a distinction
 * a literal in a component would hide.
 *
 * A MARK'S CONSUMER IS A COMPONENT, WHICH IS WHY THESE TESTS READ THE COMPONENTS. A table built to demand is
 * a claim about what draws each mark, and no assertion over `glyphs.css` alone can make it: the file that
 * declares a mark also references it, so an orphan satisfies any check that asks the file about itself. */

import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { componentsNaming } from "../../../testing/kitSources";
import { kitStylesheet } from "../../../testing/kitStylesheets";

const GLYPH_DECLARATION = /--glyph-([a-z-]+):\s*("(?:[^"\\]|\\.)*")/g;

async function glyphTable(): Promise<Map<string, string>> {
  const css = await kitStylesheet("glyphs.css");
  const table = new Map<string, string>();
  for (const match of css.matchAll(GLYPH_DECLARATION)) table.set(match[1], match[2]);
  return table;
}

/**
 * Which slot classes reach each mark, read from the rules that set `--glyph`.
 *
 * A component names a SLOT and never a mark, so a mark's consumer is one hop away: the slot class whose rule
 * assigns it. `disclosure` reaches two marks and `bracketed` composes the bracket pair with whatever slot it
 * sits beside, which is why this is a mark-to-slots map rather than a pair.
 */
async function slotsByMark(): Promise<Map<string, Set<string>>> {
  const reached = new Map<string, Set<string>>();
  parse(await kitStylesheet("glyphs.css")).walkRules((rule) => {
    /* The class is matched by its tail and reassembled, because a pattern spelling the whole class name puts
     * a hyphen against a character class and reads as Tailwind's arbitrary-value form to the markup scan. */
    const slots = [...rule.selector.matchAll(/\.glyph--([a-z-]+)/g)].map(
      (match) => `glyph--${match[1]}`,
    );
    if (slots.length === 0) return;
    rule.walkDecls((declaration) => {
      for (const reference of declaration.value.matchAll(/var\(--glyph-([a-z-]+)\)/g)) {
        const mark = reference[1];
        reached.set(mark, new Set([...(reached.get(mark) ?? []), ...slots]));
      }
    });
  });
  return reached;
}

/** Every slot class the table declares, flattened out of the mark map. */
async function declaredSlots(): Promise<string[]> {
  const slots = new Set<string>();
  for (const reached of (await slotsByMark()).values()) {
    for (const slot of reached) slots.add(slot);
  }
  return [...slots].toSorted();
}

/** Every slot class the layer's components name, which is the only evidence a rule is not dead. */
async function slotsInUse(): Promise<Set<string>> {
  const slots = await declaredSlots();
  const consumers = await Promise.all(slots.map((slot) => componentsNaming(slot)));
  return new Set(slots.filter((_, index) => consumers[index].length > 0));
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

  /* The old form of this test asked `glyphs.css` whether it contained `var(--glyph-x)`, which the file that
   * declares the mark answers yes to by construction: it checked the file against itself, and an orphaned
   * mark passed. A mark's consumer is a COMPONENT naming the slot that reaches it, so the components are what
   * is read. */
  it("holds no mark no component draws, because a table is built to demand like everything else", async () => {
    const reached = await slotsByMark();
    const inUse = await slotsInUse();

    const orphaned: string[] = [];
    for (const mark of (await glyphTable()).keys()) {
      const slots = [...(reached.get(mark) ?? [])];
      if (!slots.some((slot) => inUse.has(slot))) orphaned.push(mark);
    }

    expect(orphaned).toEqual([]);
  });

  it("declares no slot class no component names, so the table carries no dead rule", async () => {
    const inUse = await slotsInUse();

    expect((await declaredSlots()).filter((slot) => !inUse.has(slot))).toEqual([]);
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
