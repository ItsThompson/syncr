/* THE GLYPH TABLE, AND THE UNIQUENESS THE TESTING STRATEGY ASKS FOR BY NAME.
 *
 * "Assert every glyph in the kit's glyph table is unique" exists because the origin marks, the pinned mark,
 * the proposal-source mark and the overlap count must not collide, even where they appear at different tiers
 * and can never co-render. A table makes that checkable; per-component literals do not.
 *
 * The marks are written as codepoints, so these tests also pin the codepoint rather than a lookalike: the
 * indeterminate mark is U+2212 MINUS SIGN and not a hyphen, which is a distinction a literal in a component
 * would hide.
 *
 * A MARK'S CONSUMER IS A COMPONENT, WHICH IS WHY THESE TESTS READ THE COMPONENTS. A table built to demand is
 * a claim about what draws each mark, and no assertion over `glyphs.css` alone can make it: the file that
 * declares a mark also references it, so an orphan satisfies any check that asks the file about itself.
 *
 * THE CARRIERS ARE READ FROM EVERY SHIPPED STYLESHEET rather than from the table's own file. A mark is drawn by
 * whatever rule sets it, and the key hint's bracket pair is set in `ui/domain/marks/marks.css`: reading the
 * table's file alone counted such a mark as reaching nothing, and it took a slot class in `glyphs.css` that no
 * longer exists to mask it. */

import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { filesUnder } from "../../../../scripts/lib/files.ts";
import { appSourceDir } from "../../../../scripts/lib/paths.ts";
import { componentsNaming, appSourceRoot } from "../../../testing/kitSources";
import { kitStylesheet } from "../../../testing/kitStylesheets";

const GLYPH_DECLARATION = /--glyph-([a-z-]+):\s*("(?:[^"\\]|\\.)*")/g;

/** The classes in one selector's subject, which is the compound after its last combinator.
 *
 * The class is matched by its tail and reassembled rather than spelled out, because a pattern naming a class
 * family puts a hyphen against a character class and `lint:markup` reads that as Tailwind's arbitrary-value
 * form: `/\.(state-[\w-]*)/` in this file fails the scan with `no-arbitrary-value`. */
function subjectClasses(selector: string): string[] {
  const subject = selector.split(/[\s>+~]+/).at(-1) ?? "";
  return [...subject.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((match) => match[1]);
}

async function glyphTable(): Promise<Map<string, string>> {
  const css = await kitStylesheet("glyphs.css");
  const table = new Map<string, string>();
  for (const match of css.matchAll(GLYPH_DECLARATION)) table.set(match[1], match[2]);
  return table;
}

/**
 * Which classes reach each mark, read from every rule that draws one.
 *
 * A component names a CLASS and never a mark, so a mark's consumer is one hop away: the class whose rule
 * assigns it. A mark may be reached by more than one, which is why this is a mark-to-classes map rather than a
 * pair: the bracket pair is composed by the key hint's own rules, and the slot classes assign the rest.
 *
 * ONLY THE SELECTOR'S SUBJECT CARRIES THE MARK. An ancestor in a compound selector is a condition on when the
 * mark is drawn, not a thing that draws it, so counting it as a carrier would let a live ancestor answer for a
 * dead mark-bearing class: `.state-row[data-at-risk] .state-mark` is drawn on `.state-mark`, and a component
 * that stopped naming that class would have been covered by the row it sits in.
 */
async function classesByMark(): Promise<Map<string, Set<string>>> {
  const reached = new Map<string, Set<string>>();
  const sheets = await filesUnder(appSourceDir, [".css"]);
  const contents = await Promise.all(sheets.map((sheet) => readFile(sheet, "utf8")));
  for (const css of contents) {
    parse(css).walkRules((rule) => {
      const classes = rule.selectors.flatMap(subjectClasses);
      if (classes.length === 0) return;
      rule.walkDecls((declaration) => {
        for (const reference of declaration.value.matchAll(/var\(--glyph-([a-z-]+)\)/g)) {
          const mark = reference[1];
          reached.set(mark, new Set([...(reached.get(mark) ?? []), ...classes]));
        }
      });
    });
  }
  return reached;
}

/** Every class the shipped stylesheets draw a mark with, flattened out of the mark map. */
async function drawingClasses(): Promise<string[]> {
  const classes = new Set<string>();
  for (const reached of (await classesByMark()).values()) {
    for (const className of reached) classes.add(className);
  }
  return [...classes].toSorted();
}

/** Every drawing class the application's components name, which is the only evidence a rule is not dead.
 *
 * Read from the whole application rather than from the primitives layer, because the table is the KIT's and its
 * consumers are wherever a mark is drawn: the dialog's dismiss control is a primitive, and the origin marks,
 * the pin, the proposal source and the overlap count are drawn by domain components. */
async function classesInUse(): Promise<Set<string>> {
  const classes = await drawingClasses();
  const consumers = await Promise.all(
    classes.map((className) => componentsNaming(className, appSourceRoot)),
  );
  return new Set(classes.filter((_, index) => consumers[index].length > 0));
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
   * mark passed. A mark's consumer is a COMPONENT naming the class whose rule draws it, so the components are
   * what is read. */
  it("holds no mark no component draws, because a table is built to demand like everything else", async () => {
    const reached = await classesByMark();
    const inUse = await classesInUse();

    const orphaned: string[] = [];
    for (const mark of (await glyphTable()).keys()) {
      const classes = [...(reached.get(mark) ?? [])];
      if (!classes.some((className) => inUse.has(className))) orphaned.push(mark);
    }

    expect(orphaned).toEqual([]);
  });

  it("leaves no rule drawing a mark for a class no component names", async () => {
    const inUse = await classesInUse();

    expect((await drawingClasses()).filter((className) => !inUse.has(className))).toEqual([]);
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

  it("draws the indeterminate mark with the minus sign rather than a hyphen", async () => {
    const table = await glyphTable();

    expect(table.get("minus")).not.toContain("-");
  });

  it("states the bracketed form once, so both halves come from the table rather than a literal", async () => {
    const table = await glyphTable();
    const carriers = await classesByMark();
    const open = [...(carriers.get("bracket-open") ?? [])].toSorted();

    expect(table.get("bracket-open")).toBe('"[ "');
    expect(table.get("bracket-close")).toBe('" ]"');
    expect(open).not.toEqual([]);
    expect(open).toEqual([...(carriers.get("bracket-close") ?? [])].toSorted());
  });

  /* Every slot is named after the mark it holds, with no exception: a slot named for a meaning would put the
   * same declaration in the file twice under two names, and the marks a reader can never see at once share one
   * entry instead. */
  it("names every slot after its mark rather than after a meaning", async () => {
    const css = await kitStylesheet("glyphs.css");
    const slots = [
      ...css.matchAll(/\.glyph--([a-z-]+)\s*\{\s*--glyph:\s*var\(--glyph-([a-z-]+)\)/g),
    ];

    expect(slots.length).toBeGreaterThan(3);
    for (const [, slot, mark] of slots) expect(slot).toBe(mark);
  });
});
