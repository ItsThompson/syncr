/* THE PRIMITIVES LAYER'S OWN RULES, ASSERTED OVER ITS STYLESHEETS.
 *
 * Four claims in the ticket are about the kit as a whole rather than about any one component, so they are
 * checked over every stylesheet in the layer:
 *
 *   every state except hover survives forced-colors mode
 *   --shadow-hard is named in exactly one file, and it is the overlay family's
 *   no component declares its own focus ring, because the ring is scoped to the surface
 *   no component restates a token's value
 *
 * A test over the files is the honest form for all four, and the readers they rest on live in
 * `src/testing/layerRules.ts` so the layout and domain layers ask the same question of their own
 * directories. jsdom applies no stylesheet, so a rendered element says nothing about what a rule declares,
 * and forced-colors mode cannot be entered in a headless DOM at all: what CAN be checked is the property a
 * state spends, which is exactly what the design language's own reasoning turns on. */

import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { componentsNaming, appSourceRoot } from "../../../testing/kitSources";
import { primitivesDir } from "../../../testing/kitStylesheets";
import {
  HOVER,
  declaredClasses,
  forcedColorsCasualties,
  layerStylesheets,
  propertiesByState,
  stateRules,
} from "../../../testing/layerRules";

const sheets = () => layerStylesheets(primitivesDir);
/* The consumers are read from the whole application rather than from the layer, because a kit class is
 * legitimately named by a layout or a domain component. */
const classesByStylesheet = () => declaredClasses(primitivesDir);

describe("forced-colors mode", () => {
  it("reads the layer's state rules at all, so this check cannot pass on an empty list", async () => {
    expect((await propertiesByState(primitivesDir)).size).toBeGreaterThan(8);
  });

  it("leaves every state except hover with something that survives it", async () => {
    expect(await forcedColorsCasualties(primitivesDir)).toEqual([]);
  });

  /* Hover IS the casualty, and the test above is what enforces that it is the only one. What is worth pinning
   * here is that the casualty is the same everywhere: one hover fill in the kit, at --state-hover, so a
   * surface cannot quietly hover to a different wash. The tertiary button's hover also thickens its underline,
   * which happens to survive forced colors; that is a bonus rather than a requirement. */
  it("spends one fill everywhere it spends one, so there is a single hover in the kit", async () => {
    const fills = (await stateRules(primitivesDir))
      .filter((rule) => rule.state.includes(HOVER))
      .flatMap((rule) =>
        rule.declarations.filter(([property]) => property.startsWith("background")),
      );

    expect(fills.length).toBeGreaterThan(0);
    for (const [, value] of fills) expect(value).toBe("var(--state-hover)");
  });
});

describe("the one hard offset", () => {
  it("is declared in exactly one stylesheet in the layer", async () => {
    const declaring: string[] = [];
    for (const { name, css } of await sheets()) {
      parse(css).walkDecls((declaration) => {
        if (declaration.value.includes("--shadow-hard")) declaring.push(name);
      });
    }

    expect([...new Set(declaring)]).toEqual(["overlay.css"]);
  });

  /* Declaring the shadow once and CARRYING it are two different claims, and only the first was checked: a
   * count of declarations cannot see a fourth component taking the class. So the carriers are enumerated
   * here, which is what makes the paragraph in `overlay.css` falsifiable. The select's list is one of them
   * because Radix draws a real popover where the reference sheet has a native control, and the command
   * palette is not: `Command` is the control, and the domain component that floats it composes the overlay. */
  it("is carried by exactly the three surfaces that float over the page", async () => {
    expect(await componentsNaming("overlay")).toEqual([
      "DatePicker.tsx",
      "Dialog.tsx",
      "Select.tsx",
    ]);
  });

  it("is the only shadow the layer declares, so nothing else lifts off the page", async () => {
    for (const { name, css } of await sheets()) {
      const shadows: string[] = [];
      parse(css).walkDecls((declaration) => {
        if (declaration.prop === "box-shadow") shadows.push(declaration.value);
      });
      for (const shadow of shadows) {
        expect(shadow, `${name} declares a second shadow`).toBe("var(--shadow-hard)");
      }
    }
  });
});

describe("the focus ring", () => {
  /* The ring is chosen by the surface it LANDS on, so the rule is scoped to a container in `base.css` and a
   * control declares none of its own. The one exception is the keyboard cursor, which is a ring at a negative
   * offset because rows pitch at --h-row and an outset ring would be clipped by the row above. */
  it("is declared by no component, because it belongs to the surface", async () => {
    for (const { name, css } of await sheets()) {
      const outlines: string[] = [];
      parse(css).walkRules((rule) => {
        rule.walkDecls((declaration) => {
          if (declaration.prop.startsWith("outline")) outlines.push(`${name} ${rule.selector}`);
        });
      });
      for (const site of outlines) expect(site).toContain("data-highlighted");
    }
  });

  it("is never removed, in any spelling", async () => {
    for (const { name, css } of await sheets()) {
      parse(css).walkDecls((declaration) => {
        if (!declaration.prop.startsWith("outline")) return;
        expect(`${name}: ${declaration.value}`).not.toMatch(/^\S+: (none|0)$/);
      });
    }
  });
});

describe("every rule the layer ships", () => {
  /* A rule nobody names is downloaded by every reader and drawn for none of them, and two of them shipped:
   * `.calendar__step` outlived the month-step control it styled, which is now a Button, and `.calendar__cell`
   * was superseded by `.calendar__day`. A second undeclared button style sitting beside the four the design
   * language sanctions is the part that matters, and no check could see it. */
  it("declares more than one class, so this check cannot pass on an empty selector list", async () => {
    expect((await classesByStylesheet()).size).toBeGreaterThan(50);
  });

  it("is named by something the application renders", async () => {
    const declared = await classesByStylesheet();
    const consumers = await Promise.all(
      [...declared.keys()].map((className) => componentsNaming(className, appSourceRoot)),
    );
    const dead = [...declared.entries()]
      .filter((_, index) => consumers[index].length === 0)
      .map(([className, sheet]) => `${sheet} declares .${className}, which nothing names`);

    expect(dead).toEqual([]);
  });
});

describe("every value the layer draws with", () => {
  /* A component reads tokens rather than restating their values. A raw colour is the case that matters, since
   * a length is often genuinely layer-2 geometry: 22px for a stepper button is a decision this file makes,
   * while #16307F would be a pigment nobody sealed. */
  it("is a token where it is a colour", async () => {
    for (const { name, css } of await sheets()) {
      expect(`${name} ${css}`).not.toMatch(/#[0-9a-f]{3,8}\b/i);
      expect(`${name} ${css}`).not.toMatch(/\b(?:rgba?|hsla?|oklch)\s*\(/i);
    }
  });

  it("reaches no layer 0 ramp step", async () => {
    for (const { name, css } of await sheets()) {
      expect(`${name} ${css}`).not.toMatch(/--(?:cobalt|cream|oxide|verdigris|amber)-\d/);
      expect(`${name} ${css}`).not.toMatch(/--pigment-area-/);
    }
  });
});
