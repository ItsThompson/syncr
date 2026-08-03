/* THE LAYER'S OWN RULES, ASSERTED OVER ITS STYLESHEETS.
 *
 * Four claims in the ticket are about the kit as a whole rather than about any one component, so they are
 * checked over every stylesheet in the layer:
 *
 *   every state except hover survives forced-colors mode
 *   --shadow-hard is named in exactly one file, and it is the overlay family's
 *   no component declares its own focus ring, because the ring is scoped to the surface
 *   no component restates a token's value
 *
 * A test over the files is the honest form for all four. jsdom applies no stylesheet, so a rendered element
 * says nothing about what a rule declares, and forced-colors mode cannot be entered in a headless DOM at
 * all: what CAN be checked is the property a state spends, which is exactly what the design language's own
 * reasoning turns on. */

import { readdir } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { componentsNaming } from "../../../testing/kitSources";
import { kitStylesheet, primitivesDir } from "../../../testing/kitStylesheets";

async function stylesheetNames(): Promise<string[]> {
  const entries = await readdir(primitivesDir);
  return entries.filter((entry) => entry.endsWith(".css")).toSorted();
}

async function sheets(): Promise<{ name: string; css: string }[]> {
  const names = await stylesheetNames();
  return Promise.all(names.map(async (name) => ({ name, css: await kitStylesheet(name) })));
}

/* Properties forced-colors mode overrides or drops, plus the ones that are invisible in a rendering. A state
 * carried ONLY by these does not survive it, which is the whole of the design language's argument for pairing
 * a fill with a rule or a glyph. A border COLOUR is not here: it is forced to the system's text colour, and a
 * border drawn transparent at rest therefore becomes visible, which is how the current row survives. */
const NOT_A_SURVIVING_MARK = new Set([
  "background",
  "background-color",
  "background-image",
  "color",
  "box-shadow",
  "cursor",
]);

/** Selectors that name a state: a data attribute, an ARIA state, or a state pseudo-class. */
const STATE_SELECTOR =
  /\[(data-\w[\w-]*|aria-(?:invalid|selected|current|disabled|expanded))[^\]]*\]|:hover|:disabled/g;
const HOVER = ":hover";

interface StateRule {
  readonly sheet: string;
  readonly state: string;
  readonly selector: string;
  readonly declarations: readonly (readonly [string, string])[];
}

/** Every rule that styles a state, keyed by the state its selector names. */
async function stateRules(): Promise<StateRule[]> {
  const rules: StateRule[] = [];
  for (const { name, css } of await sheets()) {
    parse(css).walkRules((rule) => {
      const states = [...rule.selector.matchAll(STATE_SELECTOR)].map((match) => match[0]);
      if (states.length === 0) return;
      const declarations: (readonly [string, string])[] = [];
      rule.walkDecls((declaration) => {
        declarations.push([declaration.prop, declaration.value]);
      });
      if (declarations.length === 0) return;
      for (const state of states) {
        rules.push({ sheet: name, state, selector: rule.selector, declarations });
      }
    });
  }
  return rules;
}

/**
 * Each state in each stylesheet, with every property that state spends there.
 *
 * Grouped by file rather than by rule, because a state is legitimately carried by two rules: a disabled
 * control dashes its own border and mutes the label beside it, and the state survives on the strength of the
 * dash. Judging a rule at a time would call the second rule a casualty while the state is perfectly visible.
 */
async function propertiesByState(): Promise<Map<string, Set<string>>> {
  const spent = new Map<string, Set<string>>();
  for (const rule of await stateRules()) {
    const key = `${rule.sheet} ${rule.state}`;
    const properties = spent.get(key) ?? new Set<string>();
    for (const [property] of rule.declarations) properties.add(property);
    spent.set(key, properties);
  }
  return spent;
}

describe("forced-colors mode", () => {
  it("reads the layer's state rules at all, so this check cannot pass on an empty list", async () => {
    expect((await propertiesByState()).size).toBeGreaterThan(8);
  });

  it("leaves every state except hover with something that survives it", async () => {
    const casualties: string[] = [];
    for (const [state, properties] of await propertiesByState()) {
      if (state.includes(HOVER)) continue;
      const survives = [...properties].some((property) => !NOT_A_SURVIVING_MARK.has(property));
      if (!survives) casualties.push(state);
    }

    expect(casualties).toEqual([]);
  });

  /* Hover IS the casualty, and the test above is what enforces that it is the only one. What is worth pinning
   * here is that the casualty is the same everywhere: one hover fill in the kit, at --state-hover, so a
   * surface cannot quietly hover to a different wash. The tertiary button's hover also thickens its underline,
   * which happens to survive forced colors; that is a bonus rather than a requirement. */
  it("spends one fill everywhere it spends one, so there is a single hover in the kit", async () => {
    const fills = (await stateRules())
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
