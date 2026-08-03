/* THE PIGMENT POLICY, COMPUTED AND ENFORCED RATHER THAN DOCUMENTED.
 *
 * Four rules govern where a signal pigment may appear, and three of them are the kind that a screen breaks by
 * accident because the result looks fine to the person who wrote it:
 *
 *   pigment carries KIND, and volume carries loudness. A notice's kind is its pigment plus its mark
 *   AMBER HAS NO TEXT STEP: an amber indicator pairs with --text-muted text, and its marker sits on raised paper
 *   secondary text on a signal WASH steps to --ink-soft, never --text-muted, which fails AA there
 *   oxide and verdigris each have a text step, and label ink uses it rather than the marker step
 *
 * The ratios are computed from the token files, so a retuned pigment fails a test rather than reaching a review.
 * The structural half is read over the kit's stylesheets: a signal on PROSE is refused wherever the selector is
 * not a glyph, which is the shape of the rule the design language actually states. */

import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { INDICATOR_FLOOR, TEXT_FLOOR, ratioBetween } from "../../../testing/contrast";
import { componentSources } from "../../../testing/kitSources";
import { domainDir, layoutDir, primitivesDir } from "../../../testing/kitStylesheets";
import { layerStylesheets } from "../../../testing/layerRules";

const SIGNALS = ["--signal-amber", "--signal-oxide", "--signal-verdigris"] as const;
const KIT_DIRECTORIES = [primitivesDir, layoutDir, domainDir];

/** Which classes reach an element that also carries a glyph, read from the class lists the components write. */
async function markClasses(): Promise<Set<string>> {
  const perDirectory = await Promise.all(KIT_DIRECTORIES.map((dir) => componentSources(dir)));
  const carriers = new Map<string, boolean>();
  for (const sources of perDirectory) {
    for (const source of sources) {
      for (const classList of source.classLists) {
        const tokens = classList.split(/\s+/).filter((token) => token !== "");
        const carriesGlyph = tokens.some((token) => token.startsWith("glyph"));
        for (const token of tokens) {
          carriers.set(token, (carriers.get(token) ?? true) && carriesGlyph);
        }
      }
    }
  }
  return new Set([...carriers].filter(([, always]) => always).map(([token]) => token));
}

/** Every stylesheet in the kit, flattened across the three layers. */
async function kitSheets(): Promise<{ name: string; css: string }[]> {
  const perDirectory = await Promise.all(KIT_DIRECTORIES.map((dir) => layerStylesheets(dir)));
  return perDirectory.flat();
}

/** Every rule in the kit that sets a text colour, with the class it lands on. */
async function textColourRules(): Promise<{ where: string; target: string; value: string }[]> {
  const found: { where: string; target: string; value: string }[] = [];
  for (const { name, css } of await kitSheets()) {
    parse(css).walkRules((rule) => {
      const classes = [...rule.selector.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((match) => match[1]);
      rule.walkDecls((declaration) => {
        if (declaration.prop !== "color") return;
        found.push({
          where: `${name} ${rule.selector}`,
          target: classes.at(-1) ?? "",
          value: declaration.value,
        });
      });
    });
  }
  return found;
}

/**
 * The rules that put one of the marker steps on something that is not a mark.
 *
 * A signal pigment is sealed to markers: dots, rules, glyphs and their labels. So the question a rule has to answer
 * is whether the element it colours IS a mark, and only the components know that: `.notice__mark` is a mark because
 * `NoticeMark` writes `glyph notice__mark`, and a list beside this test would be a list somebody wrote rather than
 * a fact about the kit.
 */
async function signalOnProse(pigments: readonly string[]): Promise<string[]> {
  const marks = await markClasses();
  return (await textColourRules())
    .filter((rule) => pigments.some((pigment) => rule.value.includes(pigment)))
    .filter((rule) => !marks.has(rule.target))
    .map((rule) => rule.where);
}

describe("amber", () => {
  it("clears the indicator floor on raised paper, which is the surface its marker sits on", async () => {
    const ratio = await ratioBetween("--signal-amber", "--paper-raised");

    expect(ratio).toBeGreaterThanOrEqual(INDICATOR_FLOOR);
    expect(ratio.toFixed(2)).toBe("4.52");
  });

  it("has no text step, because a label has to clear the floor on EVERY surface it can reach", async () => {
    /* 4.52:1 on raised paper and 4.18:1 on the page. The marker passes on both, since 3:1 is its bar; a label
     * would pass on one surface and fail on the other, and "every surface it can appear on" is the rule. */
    expect(await ratioBetween("--signal-amber", "--paper-raised")).toBeGreaterThanOrEqual(
      TEXT_FLOOR,
    );
    expect(await ratioBetween("--signal-amber", "--paper")).toBeLessThan(TEXT_FLOOR);
    expect((await ratioBetween("--signal-amber", "--paper")).toFixed(2)).toBe("4.18");
  });

  /* The consequence: an amber notice's title is --text-muted rather than its own ink. Asserted over the rules that
   * set a colour, so a screen cannot quietly give amber a label. */
  it("appears on no prose anywhere in the kit, only on a mark", async () => {
    expect(await signalOnProse(["--signal-amber"])).toEqual([]);
  });
});

describe("oxide and verdigris", () => {
  it("each have a text step that clears the text floor", async () => {
    expect(await ratioBetween("--oxide-ink", "--paper-raised")).toBeGreaterThanOrEqual(TEXT_FLOOR);
    expect(await ratioBetween("--verdigris-ink", "--paper-raised")).toBeGreaterThanOrEqual(
      TEXT_FLOOR,
    );
  });

  it("keep their marker steps for markers, which is where 3:1 is the bar", async () => {
    expect(await ratioBetween("--signal-oxide", "--paper-raised")).toBeGreaterThanOrEqual(
      INDICATOR_FLOOR,
    );
    expect(await ratioBetween("--signal-verdigris", "--paper-raised")).toBeGreaterThanOrEqual(
      INDICATOR_FLOOR,
    );
  });

  /* The marker step on prose is the mistake this catches: it looks like the right colour and measures below the
   * floor a label has to clear. A mark is exempt, because a mark IS a marker, and which classes are marks is read
   * from the class lists the components write rather than from a list beside this test. */
  it("put no marker step on prose anywhere in the kit", async () => {
    expect(await signalOnProse(SIGNALS)).toEqual([]);
  });

  it("are read from real rules, so the two checks above cannot pass on an empty list", async () => {
    const signalRules = (await textColourRules()).filter((rule) =>
      SIGNALS.some((signal) => rule.value.includes(signal)),
    );

    expect(signalRules.length).toBeGreaterThan(3);
  });
});

describe("secondary text on a signal wash", () => {
  it("steps to --ink-soft, because --text-muted fails AA there", async () => {
    expect((await ratioBetween("--text-muted", "--amber-wash")).toFixed(2)).toBe("4.31");
    expect(await ratioBetween("--text-muted", "--amber-wash")).toBeLessThan(TEXT_FLOOR);
    expect(await ratioBetween("--text-on-wash", "--amber-wash")).toBeGreaterThanOrEqual(TEXT_FLOOR);
  });

  it("is safe on the two paper surfaces, which is why --text-muted is not banned outright", async () => {
    expect(await ratioBetween("--text-muted", "--paper")).toBeGreaterThanOrEqual(TEXT_FLOOR);
    expect(await ratioBetween("--text-muted", "--paper-raised")).toBeGreaterThanOrEqual(TEXT_FLOOR);
  });

  /* No component in the kit fills with a signal wash yet: the infeasibility panel is the one surface that will,\n   * and it arrives with the verdict panel. This is the check that will meet it. */
  it("is not paired with --text-muted by any rule that fills with a wash", async () => {
    const offenders: string[] = [];
    for (const { name, css } of await kitSheets()) {
      parse(css).walkRules((rule) => {
        const declarations = new Map<string, string>();
        rule.walkDecls((declaration) => {
          declarations.set(declaration.prop, declaration.value);
        });
        const fill = declarations.get("background") ?? declarations.get("background-color") ?? "";
        if (!/--(?:amber|oxide|verdigris)-wash/.test(fill)) return;
        if (declarations.get("color")?.includes("--text-muted") === true) {
          offenders.push(`${name} ${rule.selector}`);
        }
      });
    }

    expect(offenders).toEqual([]);
  });
});
