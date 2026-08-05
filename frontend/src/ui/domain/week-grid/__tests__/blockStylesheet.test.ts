/* THE BLOCK'S ANATOMY AND ITS CHANNELS, READ OUT OF THE STYLESHEET THE BROWSER LOADS.
 *
 * jsdom applies no stylesheet, so a rendered element says nothing about what a rule declares. What the design
 * language's own arguments turn on is the DECLARATION: which edges a block draws, which property each state spends,
 * and whether a state pairs its fill with something forced-colors mode keeps. All three are answerable by reading
 * the file, and none is answerable by reading the DOM.
 *
 * Each claim is bounded by the INVENTORY of what may exist rather than by a list of what may not: the edges are
 * asserted as the exact set of border properties the resting block declares, and the pigment classes as the exact
 * set of ramp steps, so a fourth edge or a thirteenth step is a failure rather than something the test is silent
 * about. */

import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { codeWithoutComments } from "../../../../../scripts/lib/css-scan.ts";
import { AREA_PIGMENTS } from "../../marks";
import { componentsNaming } from "../../../../testing/kitSources";
import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { declarationsOf, stateRules } from "../../../../testing/layerRules";

const sheet = (name: string): Promise<string> => kitStylesheet(`week-grid/${name}`, domainDir);

/** A sheet with its prose blanked, so a rule stated in a comment cannot answer a question about the code. */
async function code(name: string): Promise<string> {
  return codeWithoutComments(await sheet(name));
}

/** The declarations one selector makes, exactly as written, in the sheet's own order. */
async function rule(name: string, selector: string): Promise<[string, string][]> {
  const found: [string, string][] = [];
  parse(await sheet(name)).walkRules((each) => {
    if (each.selector !== selector) return;
    each.walkDecls((declaration) => {
      found.push([declaration.prop, declaration.value]);
    });
  });
  return found;
}

async function properties(name: string, selector: string): Promise<string[]> {
  return (await rule(name, selector)).map(([property]) => property);
}

describe("the block draws three edges, not four", () => {
  it("declares a top rule, a bottom rule, and nothing on the right", async () => {
    const borders = (await properties("block.css", ".week-block")).filter((property) =>
      property.startsWith("border"),
    );

    expect(borders).toEqual(["border-top", "border-bottom"]);
  });

  it("draws the top rule at the emphasised weight, in the Area's own ink", async () => {
    const declarations = await rule("block.css", ".week-block");

    expect(declarations).toContainEqual(["border-top", "var(--rule-emphasis) solid var(--ai)"]);
  });

  it("closes the block at grid weight, which is the hairline", async () => {
    const declarations = await rule("block.css", ".week-block");

    expect(declarations).toContainEqual(["border-bottom", "var(--hairline) solid var(--rule)"]);
  });

  it("reserves the left rule for state by composing the kit's own row states", async () => {
    /* The 3px transparent left rule and hover's fill are both assigned in `primitives/states.css`, and a second
     * definition of either drifts apart with nothing on a rendered screen revealing it until they co-occur. */
    const rows = await componentsNaming("state-row", domainDir);

    expect(rows).toContain("week-grid/Block.tsx");
    expect(await properties("block.css", ".week-block")).not.toContain("border-left");
  });

  it("names no right border anywhere in the sheet, at any state", async () => {
    const rights = (await declarationsOf(domainDir, "border-right")).filter(({ sheet: name }) =>
      name.startsWith("week-grid/block"),
    );

    expect(rights).toEqual([]);
  });

  it("insets itself from the column edges through the component, so its own rules miss the divider", async () => {
    /* The inset rides on the per-block `left` and `right`, because those carry the overlap share too: a rule in the
     * sheet would be overridden by the share the moment a column split, which is how an earlier rendering put the
     * leftmost block's bottom rule on top of the divider it was meant to sit beside. */
    const naming = await componentsNaming("week-block", domainDir);

    expect(naming).toContain("week-grid/Block.tsx");
  });
});

describe("the title wraps and never truncates", () => {
  it("sets no `white-space: nowrap`, anywhere in the sheet's code", async () => {
    expect(await code("block.css")).not.toMatch(/white-space\s*:\s*nowrap/);
  });

  it("sets no text-overflow in the family, so nothing here can end in an ellipsis", async () => {
    const inFamily = (await declarationsOf(domainDir, "text-overflow")).filter(({ sheet: name }) =>
      name.startsWith("week-grid/"),
    );

    expect(inFamily).toEqual([]);
  });

  it("clamps to a computed line count rather than to a fixed one", async () => {
    const declarations = await rule("block.css", ".week-block__title");

    expect(declarations).toContainEqual(["-webkit-line-clamp", "var(--lines)"]);
  });

  it("breaks a long word rather than overflowing the column with it", async () => {
    const declarations = await rule("block.css", ".week-block__title");

    expect(declarations).toContainEqual(["overflow-wrap", "anywhere"]);
  });
});

describe("the Area ramp reaches a block as one class per step", () => {
  it("declares exactly the twelve steps the sealed ramp holds, and no thirteenth", async () => {
    const declared: string[] = [];
    parse(await sheet("block.css")).walkRules((each) => {
      const match = /^\.week-block--area-(\d\d)$/.exec(each.selector);
      if (match !== null) declared.push(match[1]);
    });

    expect(declared).toEqual([...AREA_PIGMENTS]);
  });

  it("sets the Area's ink and nothing else, so identity stays on the top rule alone", async () => {
    const declared = await Promise.all(
      AREA_PIGMENTS.map((step) => rule("block.css", `.week-block--area-${step}`)),
    );

    expect(declared).toEqual(AREA_PIGMENTS.map((step) => [["--ai", `var(--area-${step})`]]));
  });
});

/* THE CHANNEL MAP, ASSERTED AS THE EXACT SET OF (STATE, PROPERTY) PAIRS THE SHEET DECLARES.
 *
 * Bounded rather than sampled: a state spending a second property, or a new state arriving with no entry, both fail
 * here. `scripts/check-channels` refuses a second FILE assigning a pair; this says what this file assigns. */
describe("one state, one channel", () => {
  it("spends exactly the pairs the design language deals the block", async () => {
    const spent = (await stateRules(domainDir))
      .filter((each) => each.sheet.startsWith("week-grid/"))
      .map(
        (each) => `${each.state} -> ${each.declarations.map(([property]) => property).join(", ")}`,
      )
      .toSorted();

    expect(spent).toEqual([
      "[data-conflict] -> border-left-color",
      "[data-conflict] -> border-left-width",
      "[data-dragging] -> border-top-color",
      '[data-origin="anchor"] -> border-top-color',
      '[data-origin="frame"] -> background-color',
      "[data-proposal] -> border, border-left, background-color, background-image",
      "[data-selected] -> border-left-color",
      "[data-selected] -> border-left-width",
      "[data-split] -> border-left",
      "[data-split] -> border-left-width",
      "[data-split] -> border-left-width",
      '[data-tier="compact"] -> padding-top, font-size, line-height',
      '[data-tier="hairline"] -> padding, border-bottom-width',
    ]);
  });

  it("gives conflict the pixel over selected, by declaring it second", async () => {
    const source = await sheet("block.css");

    expect(source.indexOf("[data-conflict]")).toBeGreaterThan(source.indexOf("[data-selected]"));
  });

  it("declares the split's rule BEFORE the two state rules, so a state replaces its ink", async () => {
    const source = await sheet("block.css");

    expect(source.indexOf(".week-block[data-split] {")).toBeLessThan(
      source.indexOf("[data-selected]"),
    );
  });

  it("keeps the frame's fill out-specified by hover, so a state wins the channel it owns", async () => {
    /* `:where()` contributes nothing to specificity, so the frame's fill sits at the same weight as the resting
     * block's and loses to `.state-row:hover`. Without it the frame would be the one block hover cannot reach. */
    expect(await sheet("block.css")).toContain('.week-block:where([data-origin="frame"])');
  });
});

describe("the anchor's hatch", () => {
  it("is a layer of its own, because the block's own `color` paints its title", async () => {
    /* A texture in the token layer draws in --hatch-ink, which is `currentColor`: a per-element --hatch-ink cannot
     * reach a gradient declared at :root, so the element painting the texture has to spend its `color` on it. */
    const declarations = await rule("block.css", ".week-block__hatch");

    expect(declarations).toContainEqual(["color", "var(--rule)"]);
    expect(declarations).toContainEqual(["background-image", "var(--hatch-back)"]);
  });

  it("is a background IMAGE while hover is a background COLOR, so the two compose", async () => {
    const hatch = await properties("block.css", ".week-block__hatch");
    const hover = await declarationsOf(domainDir, "background-color");

    expect(hatch).toContain("background-image");
    expect(hatch).not.toContain("background-color");
    expect(hover.map(({ sheet: name }) => name)).not.toContain("week-grid/block.css:hover");
  });

  it("sits under the block's own content and over its fill", async () => {
    expect(await rule("block.css", ".week-block__hatch")).toContainEqual(["z-index", "0"]);
    expect(await rule("block.css", ".week-block__title")).toContainEqual(["z-index", "1"]);
  });
});
