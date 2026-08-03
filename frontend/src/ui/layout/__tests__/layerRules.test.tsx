/* THE LAYOUT LAYER'S OWN RULES, ASSERTED OVER ITS SOURCES AND ITS STYLESHEETS.
 *
 * Four of these are the primitives layer's claims asked of a second directory, which is why the readers live
 * in `src/testing/layerRules.ts`: a second copy of "which properties survive forced colors" is how two layers
 * come to disagree about it.
 *
 * The fifth is this layer's own and it is a boundary rather than a quality: A CONTAINER SPENDS NO STATE. Every
 * state channel in the kit is assigned in `ui/primitives/states.css`, and a container that hovered or
 * highlighted would be assigning one a second time. `check-channels` refuses that at commit; this asserts the
 * layer has nothing for it to refuse.
 *
 * Every component is also mounted, from the barrel rather than from a list beside it, so a component added to
 * the layer and not to this file has no case here and one of these tests names it. */

import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import * as layout from "..";
import { componentNamesIn } from "../../../testing/kitExports";
import { appSourceRoot, componentsNaming } from "../../../testing/kitSources";
import { layoutDir } from "../../../testing/kitStylesheets";
import {
  declaredClasses,
  forcedColorsCasualties,
  layerSources,
  layerStylesheets,
  stateRules,
} from "../../../testing/layerRules";

const sheets = () => layerStylesheets(layoutDir);

const MOUNTED: Readonly<Record<string, () => ReactElement>> = {
  Card: () => <layout.Card label="Deviation" figure="+4%" />,
  FormRow: () => (
    <layout.FormRow label="Estimate">{(field) => <input id={field.id} />}</layout.FormRow>
  ),
  Gutter: () => <layout.Gutter />,
  Pane: () => <layout.Pane label="Body">a column</layout.Pane>,
  Panel: () => <layout.Panel title="Verdict">rows</layout.Panel>,
  Rule: () => <layout.Rule />,
  StatCell: () => <layout.StatCell label="Scheduled" figure="91" />,
  Strip: () => <layout.Strip height="fixed">three readings</layout.Strip>,
};

describe("every component the layer exports", () => {
  it("is one of the eight the design language names", () => {
    expect(componentNamesIn(layout)).toEqual([
      "Card",
      "FormRow",
      "Gutter",
      "Pane",
      "Panel",
      "Rule",
      "StatCell",
      "Strip",
    ]);
  });

  it.each(Object.keys(MOUNTED))("mounts: %s", (name) => {
    const { container } = render(MOUNTED[name]());

    expect(container.firstElementChild).not.toBeNull();
  });

  it("is mounted here, so a component cannot join the barrel unrendered", () => {
    expect(Object.keys(MOUNTED).toSorted()).toEqual(componentNamesIn(layout));
  });

  /* A `className` would let a screen paste a utility into a container the design language has already
   * settled, and the markup scan only catches the arbitrary ones. Variation is a variant instead. */
  it("takes no className, because variation is a named decision rather than a caller's utility", async () => {
    for (const { name, text } of await layerSources(layoutDir)) {
      expect(text, `${name} declares a className prop`).not.toMatch(/className\??:/);
    }
  });
});

describe("a container spends no state", () => {
  it("declares no state rule anywhere in the layer", async () => {
    const spent = (await stateRules(layoutDir)).map(
      (rule) => `${rule.sheet} ${rule.selector} spends ${rule.declarations.length}`,
    );

    expect(spent).toEqual([]);
  });

  it("has no forced-colors casualty either, which follows from spending no state", async () => {
    expect(await forcedColorsCasualties(layoutDir)).toEqual([]);
  });
});

describe("the layer's stylesheets", () => {
  it("read at all, so the checks below cannot pass on an empty list", async () => {
    expect((await sheets()).map((sheet) => sheet.name)).toEqual([
      "FormRow.css",
      "Gutter.css",
      "Panel.css",
      "Rule.css",
      "StatCell.css",
      "Strip.css",
    ]);
  });

  it("carry no shadow, because the one hard offset lifts an overlay off the page", async () => {
    for (const { name, css } of await sheets()) {
      parse(css).walkDecls((declaration) => {
        expect(declaration.prop, `${name} declares a shadow`).not.toBe("box-shadow");
      });
    }
  });

  it("declare no focus ring, because the ring belongs to the surface it lands on", async () => {
    for (const { name, css } of await sheets()) {
      parse(css).walkDecls((declaration) => {
        expect(declaration.prop.startsWith("outline"), `${name} declares an outline`).toBe(false);
      });
    }
  });

  it("restate no colour, because a component reads tokens", async () => {
    for (const { name, css } of await sheets()) {
      expect(`${name} ${css}`).not.toMatch(/#[0-9a-f]{3,8}\b/i);
      expect(`${name} ${css}`).not.toMatch(/\b(?:rgba?|hsla?|oklch)\s*\(/i);
    }
  });

  it("reach no layer 0 ramp step", async () => {
    for (const { name, css } of await sheets()) {
      expect(`${name} ${css}`).not.toMatch(/--(?:cobalt|cream|oxide|verdigris|amber)-\d/);
      expect(`${name} ${css}`).not.toMatch(/--pigment-area-/);
    }
  });

  it("declare more than one class, so the check below cannot pass on an empty list", async () => {
    expect((await declaredClasses(layoutDir)).size).toBeGreaterThan(10);
  });

  it("ship no rule nothing names, read from the class lists the application writes", async () => {
    const declared = await declaredClasses(layoutDir);
    const consumers = await Promise.all(
      [...declared.keys()].map((className) => componentsNaming(className, appSourceRoot)),
    );
    const dead = [...declared.entries()]
      .filter((_, index) => consumers[index].length === 0)
      .map(([className, sheet]) => `${sheet} declares .${className}, which nothing names`);

    expect(dead).toEqual([]);
  });
});
