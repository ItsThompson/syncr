/* THE KEY HINT'S INK, AGAINST EVERY SURFACE A HOST PUTS UNDER IT.
 *
 * The hint has one form, so it cannot have one ink: `[ c ]` inside a button whose fill is ink is the page's ink
 * on ink, and the design language's own rule is that a colour clears its floor on every surface it can appear
 * on rather than on the one its author had in mind. So the mark reads a property the surface sets, and every
 * surface that sets it is measured here.
 *
 * THIS FILE READS TWO SHEETS, because the pairing is a fact about two. `marks.css` says which property the hint
 * draws from and `Button.css` says what each rank puts in it, and neither sheet alone can answer whether the
 * hint is legible. jsdom applies neither, so both are parsed and the cascade is resolved the way the kit's
 * other visual claims are.
 *
 * THE RANKS MEASURED BELOW ARE THE SHEET'S OWN LIST, not a list somebody remembered. The census reads every
 * rule in `Button.css` that writes ink and refuses one that no rendered host reaches, so a rank added without a
 * hint ink fails here rather than shipping a mark nobody can see. Every figure is computed from the token files
 * through `src/testing/contrast.ts`, so a retuned pigment fails this file. */

import { render } from "@testing-library/react";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { codeWithoutComments } from "../../../../../scripts/lib/css-scan.ts";
import { repoRoot } from "../../../../../scripts/lib/paths.ts";
import { declaredTokens } from "../../../../../scripts/lib/tokens.ts";
import { TEXT_FLOOR, ratioBetween } from "../../../../testing/contrast";
import { inkRules, surfacesUnder, tokenIn } from "../../../../testing/hostedInk";
import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { effectiveDeclarations } from "../../../../testing/visualState";
import { Button, type ButtonRank } from "../../../primitives";
import { KeyHint } from "../KeyHint";

/** The property a surface sets to tell the hint what ink to take. */
const HINT_INK = "--key-hint-ink";

const marksCss = () => kitStylesheet("marks/marks.css", domainDir);
const buttonCss = () => kitStylesheet("Button.css");

interface Host {
  readonly name: string;
  readonly rank: ButtonRank;
  readonly isDisabled?: boolean;
}

/** The hosts the button family can put under a hint: its four ranks, and disabled, which is a state of any. */
const HOSTS: readonly Host[] = [
  { name: "the ink rank", rank: "primary" },
  { name: "the secondary rank", rank: "secondary" },
  { name: "the tertiary rank", rank: "tertiary" },
  { name: "the quiet rank", rank: "quiet" },
  { name: "a disabled control", rank: "primary", isDisabled: true },
];

function hosted(host: Host): { button: Element; hint: Element } {
  const { container } = render(
    <Button rank={host.rank} isDisabled={host.isDisabled === true}>
      Confirm the day <KeyHint keys="c" />
    </Button>,
  );
  const button = container.querySelector("button");
  const hint = container.querySelector(".key-hint");
  if (button === null || hint === null) throw new Error(`${host.name} rendered no hosted hint`);
  return { button, hint };
}

/** The ink a hint ends up drawn in inside a host, and the surfaces that host puts under it. */
async function drawnInside(host: Host): Promise<{ ink: string; surfaces: readonly string[] }> {
  const { button, hint } = hosted(host);
  const rank = effectiveDeclarations({ element: button, css: await buttonCss() });
  const mark = effectiveDeclarations({ element: hint, css: await marksCss() });

  const property = tokenIn(mark.get("color"));
  const ink = tokenIn(rank.get(property) ?? `var(${property})`);
  return { ink, surfaces: surfacesUnder(rank.get("background") ?? null) };
}

describe("the key hint's ink", () => {
  it("is a property the surface sets rather than an ink the mark names for itself", async () => {
    const hint = /\.key-hint\s*\{([^}]*)\}/.exec(await marksCss())?.[1] ?? "";

    expect(hint).toContain(`color: var(${HINT_INK})`);
  });

  it("defaults to --ink-deep, which is the ink a label takes on paper", async () => {
    expect((await declaredTokens()).get(HINT_INK)).toBe("var(--ink-deep)");
  });

  /* The hint on a paper surface is unchanged, stated as the two figures --ink-deep already measured there: a
   * default that drifted to another ink would fail here rather than being noticed on a screen. */
  it.each([
    ["--paper", "13.73"],
    ["--paper-raised", "14.83"],
  ])("clears the text floor on %s at %s:1, where most hints sit", async (surface, figure) => {
    const ratio = await ratioBetween(HINT_INK, surface);

    expect(ratio).toBeGreaterThanOrEqual(TEXT_FLOOR);
    expect(ratio.toFixed(2)).toBe(figure);
  });
});

describe("the pair that makes an inverse necessary", () => {
  /* The measurement, not the anecdote: the hint was drawn in --ink-deep and the ink rank's fill is --ink, and
   * 1.29:1 is what a reader saw. It is in this file because the fix is only meaningful with the number beside
   * it, and because a retuned pair would make the whole treatment revisitable rather than quietly fine. */
  it("is the page's ink on an ink fill, at 1.29:1", async () => {
    const ratio = await ratioBetween("--ink-deep", "--ink");

    expect(ratio).toBeLessThan(TEXT_FLOOR);
    expect(ratio.toFixed(2)).toBe("1.29");
  });
});

describe("every rule the button's stylesheet writes ink in", () => {
  it("hands a hint inside it the same ink, so no rank leaves one reading the surface it replaced", async () => {
    const rules = inkRules(await buttonCss(), HINT_INK);

    expect(rules.map((rule) => `${rule.selector} -> ${rule.markInk ?? "nothing"}`)).toEqual(
      rules.map((rule) => `${rule.selector} -> ${rule.ink}`),
    );
  });

  /* The census's own control, read a second way. The claim above is a comparison of two derived lists, which an
   * empty census would satisfy while measuring nothing, so the count is crossed against a different reader:
   * postcss walks the rules and the kit's own scanner counts the declarations. */
  it("is every rule that writes one, counted by a second reader so an empty census cannot pass", async () => {
    const css = await buttonCss();
    const written = [...codeWithoutComments(css).matchAll(/(^|[\s;{])color\s*:/g)];

    expect(written.length).toBeGreaterThan(1);
    expect(inkRules(css, HINT_INK)).toHaveLength(written.length);
  });

  it("is reached by a host measured below, so the cases here are the sheet's list rather than a memory", async () => {
    const rules = inkRules(await buttonCss(), HINT_INK);
    const buttons = HOSTS.map((host) => hosted(host).button);

    const unreached = rules.filter(
      (rule) =>
        !rule.selector
          .split(",")
          .some((part) => buttons.some((button) => button.matches(part.trim()))),
    );

    expect(unreached.map((rule) => rule.selector)).toEqual([]);
  });
});

describe("the inks a hint can take", () => {
  /* THE DESIGN LANGUAGE NAMES THEM, so the prose is crossed against the sheets rather than trusted: a rank that
   * took a fifth ink would leave the document describing a system with four. The count is pinned because the
   * document states it as a number, and a number in prose is the kind of claim that goes stale silently. */
  it("is the four the design language's keyboard section names", async () => {
    const doc = await readFile(path.join(repoRoot, "docs", "DESIGN-LANGUAGE.md"), "utf8");
    const sentence =
      doc.split("\n").find((line) => line.includes("takes the ink of the surface it lands on")) ??
      "";
    const named = [...sentence.matchAll(/`(--[\w-]+)`/g)].map((match) => match[1]);

    const rules = inkRules(await buttonCss(), HINT_INK);
    const set = new Set([
      tokenIn((await declaredTokens()).get(HINT_INK)),
      ...rules.flatMap((rule) => (rule.markInk === null ? [] : [tokenIn(rule.markInk)])),
    ]);

    expect(set.size).toBe(4);
    expect([...new Set(named)].toSorted()).toEqual([...set].toSorted());
  });
});

describe.each(HOSTS)("a hint inside $name", (host) => {
  it("clears the text floor against every surface that rank can put under it", async () => {
    const { ink, surfaces } = await drawnInside(host);
    const measured = await Promise.all(
      surfaces.map(async (surface) => [surface, await ratioBetween(ink, surface)] as const),
    );

    for (const [surface, ratio] of measured) {
      expect(ratio, `${ink} on ${surface}`).toBeGreaterThanOrEqual(TEXT_FLOOR);
    }
  });
});

describe("a hint inside a primary button", () => {
  it("takes the ink rank's own ink and clears its fill at 11.50:1", async () => {
    const { ink, surfaces } = await drawnInside({ name: "the ink rank", rank: "primary" });

    expect(ink).toBe("--on-ink");
    expect(surfaces).toEqual(["--ink"]);
    expect((await ratioBetween(ink, "--ink")).toFixed(2)).toBe("11.50");
  });
});
