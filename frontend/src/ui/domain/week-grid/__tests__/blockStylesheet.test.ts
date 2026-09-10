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

import { readFile } from "node:fs/promises";
import path from "node:path";
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

  it("names no right border at any state, read as an EDGE rather than as a longhand", async () => {
    /* The first draft asserted the `border-right` longhand and would have passed a `border` shorthand, which is how
     * a proposal target came to draw one in `block-states.html`. The shorthand is expanded here, so the question is
     * which EDGES the sheet sets rather than which property names it writes. */
    const rights: string[] = [];
    parse(await sheet("block.css")).walkDecls((declaration) => {
      /* The physical shorthand and its longhands, and the LOGICAL forms too: in a left-to-right document
       * `border-inline-end`, `border-inline` and `border-block` each set the right edge, and a rule matching only
       * the physical spellings is the same longhand-shaped hole one property name over. */
      if (
        /^border(-right|-inline(-end|-start)?|-block(-end|-start)?)?(-color|-style|-width)?$/.test(
          declaration.prop,
        )
      ) {
        rights.push(`${declaration.parent?.toString().split("{")[0].trim()} ${declaration.prop}`);
      }
    });

    expect(rights).toEqual([]);
  });

  it("gets its zero right edge from the reset the bundle carries, not from a rule of its own", async () => {
    /* Worth stating because the measurement depends on it: the block is a `<button>`, and a UA draws a button with a
     * 2px outset border on all four sides. Tailwind's preflight zeroes it, and preflight is only in the BUILT sheet.
     * A probe that links `block.css` alone measures a user-agent button and reports a right border that never ships,
     * which is a false finding a reviewer already produced once. */
    expect(await sheet("block.css")).not.toMatch(/border-right/);
    expect(await code("block.css")).not.toMatch(/border:/);
  });

  it("names its own class in exactly one place, the map that also sets the Area's ink", async () => {
    /* One base class in one `cva` call, so the class list at the call site carries only what is not the block's own.
     * The INSET itself rides on the per-block `left` and `right`, because those carry the overlap share too: a rule
     * in the sheet would be overridden by the share the moment a column split, which is how an earlier rendering put
     * the leftmost block's bottom rule on top of the divider it was meant to sit beside. It is asserted through the
     * rendering, in `block.test.tsx`, because it is a computed value rather than a declaration. */
    expect(await componentsNaming("week-block", domainDir)).toEqual(["week-grid/blockPaint.ts"]);
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

  /* THE CAP IS A HEIGHT, AND THE CLAMP SHORTHAND IS REFUSED BY NAME.
   *
   * `-webkit-line-clamp: n` is `max-lines: n` PLUS `block-ellipsis: auto`, so the ellipsis rides in the shorthand
   * and neither `white-space` nor `text-overflow` governs it. Those two were the only things the first version of
   * this file asserted, and an end-ellipsis shipped behind them: at the modal thirty-minute block on the reference
   * display three sibling titles rendered as one string. Refusing the property by name is the declaration-level
   * channel; `scripts/check-render` reads the rendered pixels, which is the channel a reader perceives, and it runs
   * nowhere automatically until ticket 1352 lands, so this sweep is the armed net. */
  it("caps the title with a HEIGHT and names no line clamp, in any spelling", async () => {
    const declarations = await rule("block.css", ".week-block__title");

    expect(declarations).toContainEqual(["max-height", "calc(var(--lines) * 1lh)"]);
    expect(declarations.map(([property]) => property)).not.toContain("-webkit-line-clamp");
    expect(declarations.map(([property]) => property)).not.toContain("line-clamp");
  });

  it("names no clamp and no ellipsis anywhere in the family, read over the code", async () => {
    /* Bounded over every sheet the family ships rather than over the one rule, because the clamp reaching the title
     * through a descendant selector would draw the same ellipsis. */
    const names = ["block.css", "grid.css", "band.css", "strip.css", "tokens.css"];
    const sheets = await Promise.all(names.map(code));
    const clamps: string[] = [];
    for (const [index, source] of sheets.entries()) {
      parse(source).walkDecls((declaration) => {
        if (/line-clamp|block-ellipsis|text-overflow|white-space/.test(declaration.prop)) {
          clamps.push(`${names[index]} ${declaration.prop}: ${declaration.value}`);
        }
      });
    }

    expect(clamps).toEqual([]);
  });

  it("caps at a whole number of the element's OWN line boxes, so a clip lands on a boundary", async () => {
    /* `1lh` resolves per element, which is what lets the label tier at 13.8px and the compact tier at 9.5px share
     * one declaration: a per-tier pixel figure would need the compact line height named a second time. */
    const declarations = await rule("block.css", ".week-block__title");
    const cap = declarations.find(([property]) => property === "max-height")?.[1] ?? "";

    expect(cap).toMatch(/1lh/);
    expect(cap).toContain("var(--lines)");
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
      "[data-proposal] -> border-bottom-color, border-bottom-style, background-color",
      "[data-selected] -> border-left-color",
      "[data-selected] -> border-left-width",
      "[data-split] -> border-left",
      /* Twice, and not a slip: the pair rule `.week-block[data-split][data-selected],
       * .week-block[data-split][data-conflict]` names `data-split` in both of its selectors, and the reader reports
       * one entry per selector. Collapsing it here would hide a second rule genuinely arriving. */
      "[data-split] -> border-left-width",
      "[data-split] -> border-left-width",
      '[data-tier="compact"] -> padding-top, font-size, line-height',
      '[data-tier="hairline"] -> padding, border-bottom-width',
    ]);
  });

  it("keeps the Area's top rule on a proposal target, because identity is not a state's to spend", async () => {
    const proposal = await rule("block.css", ".week-block[data-proposal]");

    expect(proposal.map(([property]) => property)).not.toContain("border-top");
    expect(proposal.map(([property]) => property)).not.toContain("border-top-color");
    expect(proposal.map(([property]) => property)).not.toContain("border-left");
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

  /* PROPOSAL AND HOVER TIE ON SPECIFICITY, `.week-block[data-proposal]` and `.state-row:hover` both at (0,2,0), so
   * which fill lands is decided by IMPORT ORDER. `Block.tsx` imports the kit's row states first and its own sheet
   * second, which is what puts the proposal's absent fill above hover's. Reversing the two reverses the rendering,
   * and nothing else in the suite can see it. */
  it("puts the proposal's absent fill above hover's, by importing the two sheets in that order", async () => {
    const component = await readFile(path.join(domainDir, "week-grid", "Block.tsx"), "utf8");

    expect(component).toContain('import "../../primitives/states.css";');
    expect(component).toContain('import "./block.css";');
    expect(component.indexOf("../../primitives/states.css")).toBeLessThan(
      component.indexOf('import "./block.css"'),
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
    expect(await rule("block.css", ".week-block__hatch")).toContainEqual([
      "z-index",
      "var(--z-underlay)",
    ]);
    expect(await rule("block.css", ".week-block__title")).toContainEqual([
      "z-index",
      "var(--z-content)",
    ]);
  });
});
