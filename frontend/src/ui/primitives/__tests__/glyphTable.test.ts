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

import { componentsNaming, appSourceRoot } from "../../../testing/kitSources";
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

/** Every slot class the layer's components name, which is the only evidence a rule is not dead.
 *
 * Read from the whole application rather than from the primitives layer, because the table is the KIT's and its
 * consumers are wherever a mark is drawn: the dialog's dismiss control is a primitive, and the origin marks,
 * the pin, the proposal source and the overlap count are drawn by domain components. */
async function slotsInUse(): Promise<Set<string>> {
  const slots = await declaredSlots();
  const consumers = await Promise.all(slots.map((slot) => componentsNaming(slot, appSourceRoot)));
  return new Set(slots.filter((_, index) => consumers[index].length > 0));
}

describe("the glyph table", () => {
  it("holds every mark the kit draws", async () => {
    const table = await glyphTable();

    expect([...table.keys()].toSorted()).toEqual([
      "bracket-close",
      "bracket-open",
      "caret",
      "check",
      "cross",
      "meter-cell",
      "minus",
      "month-next",
      "month-previous",
      "notice-attention",
      "notice-info",
      "origin-anchor",
      "origin-frame",
      "origin-habit",
      "origin-prep",
      "origin-task",
      "origin-template-entry",
      "origin-transit",
      "overlap",
      "pinned",
      "plus",
      "proposal-source",
      "triangle-down",
      "triangle-up",
    ]);
  });

  /* ONE MARK PER ORIGIN KIND, and the domain has seven. A block whose title no longer fits is read from its
   * mark alone, so a kind with no mark is a block that says nothing at that tier. */
  it("holds a mark for each of the domain's seven origin kinds", async () => {
    const table = await glyphTable();
    const origins = [...table.keys()].filter((mark) => mark.startsWith("origin-"));

    expect(origins.toSorted()).toEqual([
      "origin-anchor",
      "origin-frame",
      "origin-habit",
      "origin-prep",
      "origin-task",
      "origin-template-entry",
      "origin-transit",
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
    expect(table.get("cross")).toBe('"\\2715"');
    expect(table.get("triangle-down")).toBe('"\\25BE"');
  });

  /* THE TWO NEAR-MISSES THE DESIGN LANGUAGE CALLS OUT BY NAME. Both pairs are directional-looking marks that
   * appear at different tiers and can never co-render, which is exactly why nothing but a check would catch a
   * collision: the pin must not be the anchor's diamond, and the proposal source must not be the transit
   * arrow. */
  it("keeps the proposal-source mark off the transit origin's arrow", async () => {
    const table = await glyphTable();

    expect(table.get("proposal-source")).not.toBe(table.get("origin-transit"));
  });

  it("keeps the pinned mark off the anchor origin's diamond", async () => {
    const table = await glyphTable();

    expect(table.get("pinned")).not.toBe(table.get("origin-anchor"));
  });

  /* A mark used by two meanings is named after its SHAPE, so the two share one entry rather than holding one
   * codepoint twice. The cross is the dialog's dismiss and a failure notice; the tick is a checked box, a
   * completed wizard step and a resolved notice. Without that naming rule the uniqueness test above would fire
   * on a pair that is deliberately one mark. */
  it("names a shared mark after its shape, which is what keeps the table unique", async () => {
    const table = await glyphTable();

    expect(table.has("dismiss")).toBe(false);
    expect((await componentsNaming("glyph--cross", appSourceRoot)).length).toBeGreaterThan(0);
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
