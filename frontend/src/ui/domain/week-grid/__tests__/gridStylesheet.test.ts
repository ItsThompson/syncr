/* THE GRID'S FRAME, ITS LINES AND ITS BANDS, READ OUT OF THE STYLESHEETS THE BROWSER LOADS.
 *
 * jsdom applies no stylesheet, so a rendered element says nothing about what a rule declares. Three of the grid's
 * rules are entirely about declarations: the band is defined by what it does NOT declare, the quarter line's
 * step-up during a drag is a value swap, and the axis holds the left edge by a position rather than by a class.
 * None is answerable by reading the DOM.
 *
 * The band's is the claim to read closely, because it is stated negatively in the design language -- no fill, no
 * Area rule, no block state -- and a negative claim is what an inventory-bounded assertion is for. */

import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { stateRules } from "../../../../testing/layerRules";

const sheet = (name: string): Promise<string> => kitStylesheet(`week-grid/${name}`, domainDir);

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

describe("the band that explains a gap", () => {
  it("takes no fill, no Area rule and no block state", async () => {
    const declarations = await rule("band.css", ".week-band");

    expect(declarations.map(([property]) => property)).not.toContain("background-color");
    /* Its edges are DOTTED and at grid weight, which is what says the band is a bound rather than an object: the
     * Area's rule is solid and emphasised, and no band draws one. */
    expect(declarations).toContainEqual(["border-top", "var(--hairline) dotted var(--rule)"]);
    expect(declarations).not.toContainEqual(["border-top", "var(--rule-emphasis) solid var(--ai)"]);
    expect(await stateRules(domainDir)).not.toContainEqual(
      expect.objectContaining({ sheet: "week-grid/band.css" }),
    );
  });

  it("draws its texture, in the ink the token names for a forbidden span", async () => {
    const declarations = await rule("band.css", ".week-band");

    expect(declarations).toContainEqual(["color", "var(--forbidden-hatch-ink)"]);
    expect(declarations).toContainEqual(["background-image", "var(--hatch-back)"]);
  });

  it("sits UNDER every block in z-order", async () => {
    const band = await rule("band.css", ".week-band");
    const block = await rule("block.css", ".week-block__hatch");

    expect(band).toContainEqual(["z-index", "var(--z-underlay)"]);
    /* The block itself takes no z-index at rest, so document order puts it above a band at the same level; the
     * pieces of the block that DO take one are all at or above the band's. */
    expect(block).toContainEqual(["z-index", "var(--z-underlay)"]);
  });

  it("carries its own ink on the label, so the words are not drawn in the hatch's", async () => {
    expect(await rule("band.css", ".week-band__label")).toContainEqual([
      "color",
      "var(--text-muted)",
    ]);
  });

  it("takes no pointer, and lets the label that is a control take one", async () => {
    /* The label is a sibling of the underlay band, so it can stay above a block that overlaps the
     * same interval. Its anchor keeps the noninteractive layer out of hit testing; the button opts in. */
    expect(await rule("band.css", ".week-band")).toContainEqual(["pointer-events", "none"]);
    expect(await rule("band.css", ".week-band__label-anchor")).toContainEqual([
      "pointer-events",
      "none",
    ]);
    expect(await rule("band.css", "button.week-band__label")).toContainEqual([
      "pointer-events",
      "auto",
    ]);
    /* On the button form only: the reading form of the same class stays a reading. */
    expect(await rule("band.css", ".week-band__label")).not.toContainEqual([
      "pointer-events",
      "auto",
    ]);
  });
});

describe("the day header", () => {
  it("keeps its fixed height while a mark uses the label size", async () => {
    expect(await rule("grid.css", ".week-day__head")).toContainEqual([
      "height",
      "var(--day-header-h)",
    ]);
    expect(await rule("grid.css", ".week-day__mark")).toContainEqual([
      "font-size",
      "var(--fs-label)",
    ]);
  });
});

describe("the grid lines", () => {
  it("draw the hour at rule weight and the quarter faint, at rest", async () => {
    expect(await rule("grid.css", ".week-grid__line--hour")).toContainEqual([
      "border-top",
      "var(--hairline) solid var(--grid-line-hour)",
    ]);
    expect(await rule("grid.css", ".week-grid__line--quarter")).toContainEqual([
      "border-top",
      "var(--hairline) solid var(--grid-line-quarter)",
    ]);
  });

  it("step the quarter up to hour weight during a drag, keyed on the grid rather than the line", async () => {
    expect(await rule("grid.css", "[data-dragging] .week-grid__line--quarter")).toEqual([
      ["border-top-color", "var(--grid-line-quarter-drag)"],
    ]);
  });
});

describe("the now rule", () => {
  it("is the emphasised weight in the one ink that says now", async () => {
    expect(await rule("grid.css", ".week-now")).toContainEqual([
      "border-top",
      "var(--now-rule) solid var(--ink-bright)",
    ]);
  });

  it("sits above every band and every block, because it is a statement about all of them", async () => {
    const now = await rule("grid.css", ".week-now");
    const band = await rule("band.css", ".week-band");

    expect(now).toContainEqual(["z-index", "var(--z-now)"]);
    expect(band).toContainEqual(["z-index", "var(--z-underlay)"]);
  });
});

describe("the axis", () => {
  it("is sticky at the left edge, so the columns scroll under it", async () => {
    const declarations = await rule("grid.css", ".week-grid__axis");

    expect(declarations).toContainEqual(["position", "sticky"]);
    expect(declarations).toContainEqual(["left", "0"]);
  });

  it("is fixed at --axis-w while the day columns share the surplus", async () => {
    expect(await rule("grid.css", ".week-grid__axis")).toContainEqual(["width", "var(--axis-w)"]);
    expect(await rule("grid.css", ".week-day")).toContainEqual(["flex", "1 1 0"]);
  });

  it("knocks out its own background behind an hour label", async () => {
    expect(await rule("grid.css", ".week-grid__hour")).toContainEqual([
      "background-color",
      "var(--paper-raised)",
    ]);
  });
});
