/* WHAT THE FAMILY'S STYLESHEET AND ITS SOURCES SAY, as opposed to what it renders.
 *
 * jsdom applies no stylesheet, so a rendered element says nothing about what a rule declares. The claims that
 * are about RULES rather than about markup live here: cobalt only including the label cell, the texture's ink,
 * the lightening step stated once, no property the design language bans, and the absence of a line chart. The
 * rendering claims live in `charts.test.tsx`, and the split is the seam between the two questions rather than a
 * line count: nothing in this file mounts a component and nothing in that one reads the sheet.
 *
 * The paint map is here too, because a class list is not a rendering: what is asserted is which ink and which
 * texture each step of the ramp maps to, which a DOM would only obscure. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { refusalFor } from "../../../../../scripts/lib/declarations.ts";
import { declaredTokens } from "../../../../../scripts/lib/tokens.ts";
import { srcDir } from "../../../../testing/compileTheme";
import { AREA_PIGMENTS } from "../../marks/pigment";
import { AREA_HATCHES, hatchFor } from "../hatch";
import { chartPaint } from "../paint";
import { UNALLOCATED } from "../series";

const chartsDir = path.join(srcDir, "ui", "domain", "charts");

/** Every source in the family, comments and all, which is what a claim about a comment has to read. */
async function familySources(): Promise<{ name: string; text: string }[]> {
  const names = [
    "AreaLegend.tsx",
    "DataBar.tsx",
    "DeviationBar.tsx",
    "MaturityMeter.tsx",
    "PieChart.tsx",
    "StackedBars.tsx",
    "WedgePatterns.tsx",
    "deviation.ts",
    "hatch.ts",
    "index.ts",
    "paint.ts",
    "series.ts",
    "wedges.ts",
  ];
  return Promise.all(
    names.map(async (name) => ({
      name,
      text: await readFile(path.join(chartsDir, name), "utf8"),
    })),
  );
}

function chartsStylesheet(): Promise<string> {
  return readFile(path.join(chartsDir, "charts.css"), "utf8");
}

/** The declarations a rule set carries, keyed by selector, so a claim about an ink can name the rule. */
async function rulesInCharts(): Promise<Map<string, Map<string, string>>> {
  const rules = new Map<string, Map<string, string>>();
  parse(await chartsStylesheet()).walkRules((rule) => {
    const declarations = rules.get(rule.selector) ?? new Map<string, string>();
    rule.walkDecls((declaration) => {
      declarations.set(declaration.prop, declaration.value);
    });
    rules.set(rule.selector, declarations);
  });
  return rules;
}

/* THERE IS NO LINE CHART IN THIS PRODUCT. The Area seal permits ink on a wedge or a bar fill, not on a line, and
 * twelve cobalt lines separated only by dash pattern is unreadable. An absence with no check is an absence that
 * comes back, so this is the check. */
describe("the line chart that does not exist", () => {
  it("is exported by nothing in the family", async () => {
    const barrel = await readFile(path.join(chartsDir, "index.ts"), "utf8");
    const exported = [...barrel.matchAll(/export \{([^}]*)\}/g)].flatMap((match) =>
      match[1].split(",").map((name) => name.trim()),
    );

    expect(exported.filter((name) => /line/i.test(name))).toEqual([]);
  });

  it("has no code path, because nothing here names one or sets a dash", async () => {
    for (const { name, text } of await familySources()) {
      expect(text, `${name} names a line chart`).not.toMatch(/LineChart|lineChart/);
      expect(text, `${name} sets a dash pattern`).not.toContain("strokeDasharray");
    }
  });

  /* EVERY SVG ELEMENT THAT CAN DRAW A LINE IS SCOPED TO THE ONE FILE THAT LEGITIMATELY DRAWS IT, because the
   * family already draws `<line>` for the stripe tiles: a rule that simply banned the element would have to be
   * suppressed there, and a rule that banned `<line points=` bans nothing at all, since `points` belongs to
   * `<polyline>` and `<polygon>`. That was the hole a reviewer measured: a real `<line x1= y1= x2= y2=>` chart
   * passed every case in this family. A stroked `<path>` is the other route to a line, so it is scoped too. */
  it("cannot arrive as an element either, because each one is scoped to its own file", async () => {
    const SCOPE: Readonly<Record<string, readonly string[]>> = {
      "<line": ["WedgePatterns.tsx"],
      "<path": ["PieChart.tsx"],
      "<polyline": [],
      "<polygon": [],
    };
    const sources = await familySources();

    for (const [element, permitted] of Object.entries(SCOPE)) {
      const drawing = sources.filter(({ text }) => text.includes(element)).map(({ name }) => name);

      expect(drawing, `${element} is drawn outside the file that owns it`).toEqual(permitted);
    }
  });

  it("draws the trend with bar fills, which is the carrier the seal permits", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".chart-fill")?.get("background-color")).toBe("var(--ai)");
    expect(rules.get(".chart-fill--hatched")?.get("background-image")).toBe("var(--hx)");
  });
});

describe("the paint map", () => {
  /* A MISDIRECT IS CAUGHT BY THE LAYER'S ORPHAN-RULE TEST AND A TRANSPOSITION IS NOT: swapping two steps' ink
   * classes leaves every class named by something, so the whole suite passed while Area 06 painted in Area 07's
   * ink and carried Area 06's texture. That breaks the pairing the ramp's adjacent-hue defence rests on, which
   * is that two neighbouring pigments carry different hatches. */
  it("gives every step of the ramp its own ink, so a transposition cannot pass", () => {
    for (const step of AREA_PIGMENTS) {
      expect(chartPaint(step, "x")).toContain(`chart-ink--${step}`);
    }
  });

  it("gives every step the texture the sealed ledger holds for it", () => {
    for (const step of AREA_PIGMENTS) {
      expect(chartPaint(step, "x")).toContain(`chart-hatch--${AREA_HATCHES[step]}`);
    }
  });

  it("gives the vacancy its own ink and no texture at all", () => {
    const painted = chartPaint(UNALLOCATED, "x");

    expect(hatchFor(UNALLOCATED)).toBeNull();
    expect(painted).toContain("chart-ink--unallocated");
    expect(painted).toContain("chart-hatch--none");
    for (const step of AREA_PIGMENTS) expect(painted).not.toContain(`chart-ink--${step}`);
  });

  it("carries the element's own classes through, which is what keeps the class list readable", () => {
    expect(chartPaint("01", "stacked__segment chart-fill")).toContain(
      "stacked__segment chart-fill",
    );
  });
});

describe("the vacancy's ink", () => {
  it("is no step of the ramp, but the token that names the vacancy", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".chart-ink--unallocated")?.get("--ai")).toBe("var(--unallocated)");
  });
});

describe("the deviation rows", () => {
  it("draw both directions in one ink, so the side is the whole encoding", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".deviation__bar")?.get("background")).toBe("var(--ink)");
    expect([...(rules.get(".deviation__bar--under") ?? [])]).toEqual([["right", "50%"]]);
    expect([...(rules.get(".deviation__bar--over") ?? [])]).toEqual([["left", "50%"]]);
  });

  /* COBALT ONLY, AND NO AREA INK ANYWHERE IN THE ROW, INCLUDING THE LABEL CELL. The rendering half of this claim
   * is in `charts.test.tsx`; this is the half no rendering can make, because a rule that named an Area ink would
   * only show up on a screen. */
  it("spend no Area ink in any rule of their own", async () => {
    const deviationRules = [...(await rulesInCharts())].filter(([selector]) =>
      selector.startsWith(".deviation"),
    );

    expect(deviationRules.length).toBeGreaterThan(5);
    for (const [selector, declarations] of deviationRules) {
      for (const [property, value] of declarations) {
        expect(`${selector} ${property}`, `${selector} spends an Area ink`).not.toMatch(
          /--ai|--hx/,
        );
        expect(value, `${selector} spends an Area ink`).not.toMatch(/--area-|--ai\b|--hx\b/);
      }
    }
  });
});

describe("the legend's chip", () => {
  it("carries no texture, because one carrier per context", async () => {
    const rules = await rulesInCharts();

    expect(rules.has(".area-chip")).toBe(false);
    expect(rules.get(".chart-fill")?.has("background-image")).toBe(false);
  });
});

describe("the two bounded-progress forms", () => {
  /* A COMMENT RECORDS WHY THE TWO DIFFER, so a later contributor does not unify them. Asserted rather than
   * trusted: the reason is what stops the next reader deleting one of the two forms. */
  it("each records why it is not the other, in the file a reader will open", async () => {
    const sources = new Map((await familySources()).map(({ name, text }) => [name, text]));

    expect(sources.get("MaturityMeter.tsx")).toContain("bounded");
    expect(sources.get("MaturityMeter.tsx")).toContain("DataBar");
    expect(sources.get("DataBar.tsx")).toContain("MaturityMeter");
    expect(sources.get("DataBar.tsx")).toContain("arbitrary magnitude");
  });
});

describe("the family's stylesheet", () => {
  /* MOTION IS ZERO, WITHOUT EXCEPTION, and the same list stylelint, the markup scan and the bundle gate read is
   * read here, so a property added to the design language reaches this test with no edit. */
  it("spends no property the design language bans", async () => {
    const offenders: string[] = [];
    parse(await chartsStylesheet()).walkDecls((declaration) => {
      const refusal = refusalFor(declaration.prop, declaration.value);
      if (refusal !== null) offenders.push(`${declaration.prop}: ${refusal}`);
    });

    expect(offenders).toEqual([]);
  });

  it("declares no keyframes, so there is nothing for a rule to reference", async () => {
    expect(await chartsStylesheet()).not.toContain("@keyframes");
  });

  it("states the hatch's lightening step once, from the token that declares it", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".chart-ink")?.get("color")).toBe(
      "color-mix(in srgb, var(--ai) var(--hatch-mix), var(--paper-raised))",
    );
    const spenders: string[] = [];
    parse(await chartsStylesheet()).walkDecls((declaration) => {
      if (declaration.value.includes("--hatch-mix")) spenders.push(declaration.prop);
    });
    expect(spenders).toEqual(["color"]);
  });

  /* THE TEXTURE'S INK IS `currentColor`, AND THAT IS THE ONLY MECHANISM THAT WORKS. A gradient declared in the
   * token layer resolves its own `var()`s against `:root`, so an element-level `--hatch-ink` cannot reach it: the
   * six textures computed to the empty string and every `background-image: var(--hatch-fwd)` computed to `none`
   * until `--hatch-ink` was declared. This is the check that keeps the chain intact from this end. */
  it("paints its texture with the ink the token layer resolves per element", async () => {
    const tokens = await declaredTokens();

    expect(tokens.get("--hatch-ink")).toBe("currentColor");
    for (const [name, value] of tokens) {
      if (!name.startsWith("--hatch-") || !value.includes("gradient(")) continue;
      for (const reference of value.matchAll(/var\((--[\w-]+)/g)) {
        expect(
          tokens.has(reference[1]),
          `${name} reads ${reference[1]}, which nothing declares`,
        ).toBe(true);
      }
    }
  });

  /* A HATCH NEVER SITS ON PAPER. It is a lighter step of its own fill and measures under 2:1 against either paper
   * surface, so a rule that painted a texture without an ink under it would put a near-invisible pattern straight
   * onto the page. */
  it("pairs every texture with an ink under it", async () => {
    const rules = await rulesInCharts();

    for (const [selector, declarations] of rules) {
      if (!declarations.has("background-image")) continue;
      const paired = rules.get(selector.replace("--hatched", ""));

      expect(
        paired?.get("background-color") ?? declarations.get("background-color"),
        `${selector} paints a texture with no ink under it`,
      ).toBe("var(--ai)");
    }
  });
});
