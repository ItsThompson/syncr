/* THE CHART FAMILY'S CONTRAST LEDGER, COMPUTED AND COMMITTED.
 *
 * Every colour pair this family introduces is measured here, against EVERY surface it can reach rather than the
 * expected one: a chart sits inside a `Panel` on the Areas screen and directly on the page elsewhere, so both
 * papers are surfaces every fill and every label can land on.
 *
 * A PAIR WITHOUT A RATIO FAILS THIS FILE. The last test reads `charts.css` back and refuses a token the family
 * paints with that the ledger below does not measure, so a new pair cannot arrive unmeasured. Every figure is
 * derived from the token files through `src/testing/contrast.ts`, so a retuned pigment fails here rather than
 * reaching a review that has to notice it by eye.
 *
 * TWO PAIRS SIT BELOW THE 3:1 INDICATOR FLOOR AND BOTH ARE RECORDED WITH THE REASON. A hatch is not an indicator:
 * it is a texture over a fill that has already cleared the floor, and its lightening step is fixed by
 * `--hatch-mix`. An unfilled meter cell is a track rather than a mark, which is why a meter is never the only
 * statement of progress. Neither is a pair the design language leaves silent by accident. */

import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { declaredTokens, resolveToken } from "../../../../../scripts/lib/tokens.ts";
import {
  INDICATOR_FLOOR,
  TEXT_FLOOR,
  contrastRatio,
  mixInSrgb,
} from "../../../../testing/contrast";
import { kitStylesheet } from "../../../../testing/kitStylesheets";
import { domainDir } from "../../../../testing/kitStylesheets";
import { AREA_PIGMENTS } from "../../marks/pigment";

const CHARTS = "charts/charts.css";

/** Every step of the ramp, measured against both paper surfaces as a wedge or a stacked-segment fill. */
const RAMP_ON_RAISED: Readonly<Record<string, string>> = {
  "01": "5.38",
  "02": "5.40",
  "03": "5.35",
  "04": "5.43",
  "05": "5.39",
  "06": "5.39",
  "07": "5.41",
  "08": "5.39",
  "09": "5.40",
  "10": "5.40",
  "11": "5.36",
  "12": "5.40",
};

const RAMP_ON_PAGE: Readonly<Record<string, string>> = {
  "01": "4.98",
  "02": "5.00",
  "03": "4.95",
  "04": "5.03",
  "05": "4.99",
  "06": "4.99",
  "07": "5.00",
  "08": "4.99",
  "09": "4.99",
  "10": "5.00",
  "11": "4.97",
  "12": "5.00",
};

/** Each hatch against the fill it is drawn on, which is the only surface it can reach. */
const HATCH_ON_ITS_FILL: Readonly<Record<string, string>> = {
  "01": "2.72",
  "02": "2.77",
  "03": "2.79",
  "04": "2.84",
  "05": "2.79",
  "06": "2.76",
  "07": "2.75",
  "08": "2.74",
  "09": "2.82",
  "10": "2.80",
  "11": "2.75",
  "12": "2.74",
};

interface LedgerRow {
  readonly foreground: string;
  readonly background: string;
  /** The computed ratio, to two decimals, so a retune fails rather than drifts. */
  readonly ratio: string;
  /** The bar this pair has to clear, or null where it is recorded rather than gated. */
  readonly floor: number | null;
  readonly carries: string;
}

const LEDGER: readonly LedgerRow[] = [
  {
    foreground: "--unallocated",
    background: "--paper-raised",
    ratio: "5.28",
    floor: INDICATOR_FLOOR,
    carries: "the vacancy's wedge and segment fill, at the ramp's own weight in no hue",
  },
  {
    foreground: "--unallocated",
    background: "--paper",
    ratio: "4.89",
    floor: INDICATOR_FLOOR,
    carries: "the same fill with the chart on the page rather than in a panel",
  },
  {
    foreground: "--ink",
    background: "--paper-raised",
    ratio: "11.50",
    floor: INDICATOR_FLOOR,
    carries: "a deviation bar, a data bar's fill, a filled meter cell, and a wedge's label",
  },
  {
    foreground: "--ink",
    background: "--paper",
    ratio: "10.65",
    floor: TEXT_FLOOR,
    carries: "the same, with a wedge label on the page: a label is text and clears the text floor",
  },
  {
    foreground: "--ink-deep",
    background: "--paper-raised",
    ratio: "14.83",
    floor: INDICATOR_FLOOR,
    carries: "the zero rule direction is read from, and a legend row's name",
  },
  {
    foreground: "--ink-deep",
    background: "--paper",
    ratio: "13.73",
    floor: TEXT_FLOOR,
    carries: "the same on the page",
  },
  {
    foreground: "--text-muted",
    background: "--paper-raised",
    ratio: "5.28",
    floor: TEXT_FLOOR,
    carries: "every caption, the column heads, the axis, a week label and a legend figure",
  },
  {
    foreground: "--text-muted",
    background: "--paper",
    ratio: "4.89",
    floor: TEXT_FLOOR,
    carries: "the same on the page",
  },
  {
    foreground: "--rule-strong",
    background: "--paper-raised",
    ratio: "2.65",
    floor: null,
    carries:
      "a stacked bar's own border and the column heads' underline. A container edge is decorative: " +
      "the design language bans this step on a control for the same 2.65:1 and sanctions it here",
  },
  {
    foreground: "--rule-strong",
    background: "--paper",
    ratio: "2.45",
    floor: null,
    carries: "the same two edges with the chart on the page rather than in a panel",
  },
  {
    foreground: "--rule",
    background: "--paper-raised",
    ratio: "1.71",
    floor: null,
    carries:
      "a track's hairline edges, a legend row's separators, and an unfilled meter cell. A hairline " +
      "and a track are not marks: the meter is never the only statement of progress",
  },
  {
    foreground: "--rule",
    background: "--paper",
    ratio: "1.59",
    floor: null,
    carries: "the same hairlines with the chart on the page",
  },
  {
    foreground: "--paper-raised",
    background: "--paper",
    ratio: "1.08",
    floor: null,
    carries:
      "a deviation track's own fill against the page. It is bounded by its two --rule edges rather " +
      "than by its fill, which is why a wash never carries meaning alone in this system",
  },
];

async function ratioOf(foreground: string, background: string): Promise<number> {
  const tokens = await declaredTokens();
  return contrastRatio(resolveToken(tokens, foreground), resolveToken(tokens, background));
}

/** The hatch a step of the ramp is drawn with, as a literal, mixed the way `charts.css` mixes it. */
async function hatchInk(step: string): Promise<string> {
  const tokens = await declaredTokens();
  const percent = Number.parseFloat(resolveToken(tokens, "--hatch-mix"));
  return mixInSrgb(
    resolveToken(tokens, `--area-${step}`),
    resolveToken(tokens, "--paper-raised"),
    percent,
  );
}

describe("the ledger", () => {
  const gated = LEDGER.filter((row) => row.floor !== null);
  const recorded = LEDGER.filter((row) => row.floor === null);

  it.each(gated)("$foreground on $background is $ratio:1, carrying $carries", async (row) => {
    const ratio = await ratioOf(row.foreground, row.background);

    expect(ratio.toFixed(2)).toBe(row.ratio);
    expect(ratio).toBeGreaterThanOrEqual(row.floor ?? INDICATOR_FLOOR);
  });

  /* Recorded rather than gated, each with the reason it clears no floor: a hairline, a track and a surface are
   * not marks, and the review checklist asks for a computed ratio rather than for a pass. */
  it.each(recorded)("$foreground on $background is $ratio:1, carrying $carries", async (row) => {
    expect((await ratioOf(row.foreground, row.background)).toFixed(2)).toBe(row.ratio);
  });

  it("gates the pairs that are marks and records the ones that are not", () => {
    expect(gated.length).toBeGreaterThan(recorded.length);
  });
});

describe("a wedge or a stacked segment in Area ink", () => {
  /* A WEDGE FILL IS AN INDICATOR, so 3:1 is its bar. The ramp is equalised to within 0.1 of 5.0:1 on the page,
   * which is what keeps one wedge from reading as heavier than another at equal area. */
  it.each(AREA_PIGMENTS)("clears the indicator floor on both papers: --area-%s", async (step) => {
    const raised = await ratioOf(`--area-${step}`, "--paper-raised");
    const page = await ratioOf(`--area-${step}`, "--paper");

    expect(raised.toFixed(2)).toBe(RAMP_ON_RAISED[step]);
    expect(page.toFixed(2)).toBe(RAMP_ON_PAGE[step]);
    expect(raised).toBeGreaterThanOrEqual(INDICATOR_FLOOR);
    expect(page).toBeGreaterThanOrEqual(INDICATOR_FLOOR);
  });

  it("stays equalised, so no wedge reads as heavier than another at equal area", async () => {
    const measured = await Promise.all(
      AREA_PIGMENTS.map((step) => ratioOf(`--area-${step}`, "--paper")),
    );

    expect(Math.max(...measured) - Math.min(...measured)).toBeLessThan(0.1);
  });

  /* THE SEPARATOR'S PAIR IS THE FILL'S OWN PAIR. A wedge is outlined in --paper-raised so two adjacent wedges
   * stay two wedges, and the ratio between that stroke and the fill is the same figure measured above. */
  it("is separated from its neighbour by a stroke at the same ratio the fill was measured at", async () => {
    const stroke = await ratioOf("--paper-raised", "--area-01");

    expect(stroke.toFixed(2)).toBe(RAMP_ON_RAISED["01"]);
    expect(stroke).toBeGreaterThanOrEqual(INDICATOR_FLOOR);
  });
});

describe("a hatch on the fill it is drawn on", () => {
  /* RECORDED RATHER THAN GATED, and the reason is not laziness. A hatch is a texture over a fill that has already
   * cleared the indicator floor, and how light it is drawn is fixed by --hatch-mix in the token layer: reaching
   * 3:1 against its own ink would need a mix no token declares. What matters is that the separation does not
   * regress, so the floor below is the measured minimum rather than a rule invented here. */
  it.each(AREA_PIGMENTS)("measures against its own ink: --area-%s", async (step) => {
    const tokens = await declaredTokens();
    const ratio = contrastRatio(await hatchInk(step), resolveToken(tokens, `--area-${step}`));

    expect(ratio.toFixed(2)).toBe(HATCH_ON_ITS_FILL[step]);
    expect(ratio).toBeGreaterThan(2.7);
  });

  /* WHICH IS WHY A TEXTURE IS NEVER PAINTED WITHOUT AN INK UNDER IT. Against either paper a hatch measures under
   * 2:1, so a background-image with no background-color would put a near-invisible pattern onto the page. The
   * structural half of that claim is asserted in `charts.test.tsx`. */
  it("would be invisible on paper, which is what pairs it with a fill", async () => {
    const tokens = await declaredTokens();
    const onPaper = await Promise.all(
      AREA_PIGMENTS.map(async (step) =>
        contrastRatio(await hatchInk(step), resolveToken(tokens, "--paper")),
      ),
    );

    expect(Math.max(...onPaper)).toBeLessThan(2);
  });
});

describe("the ledger's own coverage", () => {
  /* A PAIR WITHOUT A RATIO FAILS THE COMPONENT TEST, and the unit is the PAIR rather than the token. Keying on the
   * token alone let a new pair of an already-listed token pass: `color: var(--rule-strong)` on the caption, at
   * 2.45:1 against a 4.5 floor, was measured passing every case in this file. A chart sits inside a panel on the
   * Areas screen and on the page elsewhere, so both papers are surfaces every ink it paints with can land on, and
   * that is what makes "every surface it can reach" checkable rather than a promise. */
  const SURFACES = ["--paper-raised", "--paper"] as const;

  /** Every pair the ledger and the ramp table together measure, keyed foreground against background. */
  function measuredPairs(): Set<string> {
    const pairs = new Set(LEDGER.map((row) => `${row.foreground} on ${row.background}`));
    for (const step of AREA_PIGMENTS) {
      for (const surface of SURFACES) pairs.add(`--area-${step} on ${surface}`);
    }
    return pairs;
  }

  /** Every colour token the sheet paints with, and the rule each was found in. */
  async function paintedTokens(): Promise<Map<string, string>> {
    const PAINTS = new Set([
      "background",
      "background-color",
      "color",
      "fill",
      "stroke",
      "border",
      "border-top",
      "border-bottom",
      "border-right",
      "border-left",
      "--ai",
    ]);
    /* The sheet's own indirections: `--ai` is measured as the ramp and the vacancy, `--hatch-ink` is the texture's
     * ink and is `currentColor` rather than a colour of its own, and `--hx` and `--hxs` are a gradient and a tile
     * size. Everything else is judged by whether it RESOLVES to a colour, so a hairline width in a border
     * shorthand is not read as a pair. */
    const SHEET_LOCAL = new Set(["--ai", "--hatch-ink", "--hx", "--hxs"]);
    const tokens = await declaredTokens();
    const painted = new Map<string, string>();

    parse(await kitStylesheet(CHARTS, domainDir)).walkRules((rule) => {
      rule.walkDecls((declaration) => {
        if (!PAINTS.has(declaration.prop)) return;
        for (const reference of declaration.value.matchAll(/var\((--[\w-]+)/g)) {
          if (SHEET_LOCAL.has(reference[1])) continue;
          const value = tokens.get(reference[1]);
          if (value === undefined) continue;
          if (!/^#[0-9a-f]{6}$/i.test(resolveToken(tokens, reference[1]))) continue;
          painted.set(reference[1], `${rule.selector} { ${declaration.prop} }`);
        }
      });
    });
    return painted;
  }

  it("measures every token the family paints with, against both papers", async () => {
    const measured = measuredPairs();
    const unmeasured: string[] = [];

    for (const [token, where] of await paintedTokens()) {
      /* A paper is a surface rather than a mark on one, so it is measured against the OTHER paper and against the
       * inks it separates rather than against itself. */
      const surfaces = SURFACES.filter((surface) => surface !== token);
      for (const surface of surfaces) {
        if (measured.has(`${token} on ${surface}`)) continue;
        unmeasured.push(`${token} on ${surface}, painted by ${where}`);
      }
    }

    expect(unmeasured).toEqual([]);
  });

  /* AN INK SET AS PROSE CLEARS THE TEXT FLOOR ON BOTH PAPERS. The pair being measured is not enough on its own: a
   * recorded 2.45:1 is correct for a container edge and wrong for a caption, so the ROLE the sheet puts the ink in
   * is what decides which floor applies. */
  it("clears the text floor with every ink it sets as prose", async () => {
    /* The two rules that set `color` for something that is not prose, each with the reason. Anything else that
     * sets an ink as text has to clear 4.5:1 on both papers. */
    const NOT_PROSE: Readonly<Record<string, string>> = {
      ".chart-ink":
        "the texture's ink, delivered to a gradient through currentColor. Nothing carrying it holds text",
      ".meter__cell--empty":
        "the unfilled run, a track drawn as a character. Recorded at 1.71:1 with its reason",
    };
    const inks = new Map<string, string>();

    parse(await kitStylesheet(CHARTS, domainDir)).walkRules((rule) => {
      if (rule.selector in NOT_PROSE) return;
      rule.walkDecls((declaration) => {
        if (declaration.prop !== "color") return;
        for (const reference of declaration.value.matchAll(/var\((--[\w-]+)/g)) {
          inks.set(reference[1], rule.selector);
        }
      });
    });

    expect(inks.size).toBeGreaterThan(2);
    const ratios = await Promise.all(
      [...inks].flatMap(([ink, selector]) =>
        SURFACES.map(async (surface) => ({
          where: `${selector} { color: var(${ink}) } on ${surface}`,
          ratio: await ratioOf(ink, surface),
        })),
      ),
    );
    for (const { where, ratio } of ratios) {
      expect(ratio, `${where} measures ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(TEXT_FLOOR);
    }
  });

  it("names no rule in its not-prose list that the sheet does not declare", async () => {
    const declared = new Set<string>();
    parse(await kitStylesheet(CHARTS, domainDir)).walkRules((rule) => {
      declared.add(rule.selector);
    });

    for (const selector of [".chart-ink", ".meter__cell--empty"]) {
      expect(declared.has(selector), `${selector} is exempt from a rule it no longer has`).toBe(
        true,
      );
    }
  });

  it("reads a sheet that paints, so the checks above cannot pass on an empty scan", async () => {
    let painted = 0;
    parse(await kitStylesheet(CHARTS, domainDir)).walkDecls((declaration) => {
      if (/^(?:background|color|fill|stroke|border)/.test(declaration.prop)) painted += 1;
    });

    expect(painted).toBeGreaterThan(10);
  });
});
