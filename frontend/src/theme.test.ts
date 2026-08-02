/* Theme fencing.
 *
 * Two properties, and both are load-bearing.
 *
 * MAPPING: the stock names that survive compile to this system's values, so a contributor who
 * pastes stock markup lands on-brand without knowing the rules.
 *
 * FENCING: the stock names that cannot be reached from this system compile to NOTHING, so an
 * off-brand utility fails rather than rendering a red button or a spinner. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

import { scanCss } from "../scripts/lib/css-scan.ts";
import { compileUtilities, declarationsOf, srcDir } from "./testing/compileTheme";

/* Everything in tokens/color.css that is not a color: two texture primitives and the size and
 * mix ratio they are drawn with. Listed here so a NEW color token with no theme entry fails
 * this file rather than being silently unreachable from a utility. */
const NON_COLOR_TOKENS = new Set([
  "--hatch-fwd",
  "--hatch-back",
  "--hatch-vert",
  "--hatch-horz",
  "--hatch-cross",
  "--hatch-dot",
  "--hatch-dot-size",
  "--hatch-mix",
]);

let themeSource = "";
let colorTokens: string[] = [];
let rampSteps: Set<string>;

beforeAll(async () => {
  themeSource = await readFile(path.join(srcDir, "theme.css"), "utf8");
  const color = scanCss(await readFile(path.join(srcDir, "tokens", "color.css"), "utf8"));
  colorTokens = color.declarations
    .map((declaration) => declaration.name)
    .filter((name) => !NON_COLOR_TOKENS.has(name));
  const primitives = scanCss(await readFile(path.join(srcDir, "tokens", "primitives.css"), "utf8"));
  rampSteps = new Set(primitives.declarations.map((declaration) => declaration.name));
});

function themeEntries(namespace: string): Map<string, string> {
  const entries = new Map<string, string>();
  const pattern = new RegExp(`^\\s*(--${namespace}-[a-z0-9-]+)\\s*:\\s*([^;]+);`, "gm");
  for (const match of themeSource.matchAll(pattern)) entries.set(match[1], match[2].trim());
  return entries;
}

describe("the color namespace", () => {
  it("has one entry per layer 1 semantic name", () => {
    const mapped = [...themeEntries("color").keys()].map((key) => key.replace(/^--color-/, "--"));
    expect(mapped.toSorted()).toEqual([...colorTokens].toSorted());
  });

  it("has no entry per layer 0 ramp step", () => {
    const values = [...themeEntries("color").values()];
    const reachingLayerZero = values.filter((value) =>
      [...rampSteps].some((step) => value.includes(`var(${step})`)),
    );
    expect(reachingLayerZero).toEqual([]);
  });

  it("does not compile a stock Tailwind color", async () => {
    const css = await compileUtilities(["bg-red-500", "text-slate-700", "border-white"]);
    expect(declarationsOf(css, "bg-red-500")).toBeNull();
    expect(declarationsOf(css, "text-slate-700")).toBeNull();
    expect(declarationsOf(css, "border-white")).toBeNull();
  });

  it("does not compile a layer 0 ramp step as a utility", async () => {
    const css = await compileUtilities(["bg-cobalt-600", "text-cream-200"]);
    expect(declarationsOf(css, "bg-cobalt-600")).toBeNull();
    expect(declarationsOf(css, "text-cream-200")).toBeNull();
  });

  it("compiles a layer 1 name onto its token", async () => {
    const css = await compileUtilities(["bg-paper", "text-ink", "border-rule-strong"]);
    expect(declarationsOf(css, "bg-paper")).toBe("background-color: var(--paper);");
    expect(declarationsOf(css, "text-ink")).toBe("color: var(--ink);");
    expect(declarationsOf(css, "border-rule-strong")).toBe("border-color: var(--rule-strong);");
  });
});

describe("geometry", () => {
  it("compiles every stock radius name to zero radius", async () => {
    const names = ["rounded-xs", "rounded-sm", "rounded-md", "rounded-lg", "rounded-4xl"];
    const css = await compileUtilities(names);
    for (const name of names) {
      expect(declarationsOf(css, name)).toBe("border-radius: var(--radius);");
    }
    expect(/--radius:\s*0\s*;/.test(css)).toBe(true);
  });

  it("keeps rounded-full, which is the only rounded form the system tolerates", async () => {
    const css = await compileUtilities(["rounded-full"]);
    expect(declarationsOf(css, "rounded-full")).toBe("border-radius: calc(infinity * 1px);");
  });

  it("compiles shadow-sm to the one hard offset and drops the blurred stock shadows", async () => {
    const css = await compileUtilities(["shadow-sm", "shadow-lg", "shadow-2xl", "blur-sm"]);
    expect(declarationsOf(css, "shadow-sm")).toContain("--tw-shadow: var(--shadow-hard)");
    expect(declarationsOf(css, "shadow-lg")).toBeNull();
    expect(declarationsOf(css, "shadow-2xl")).toBeNull();
    expect(declarationsOf(css, "blur-sm")).toBeNull();
  });
});

describe("type", () => {
  it("compiles text-sm to the machine-content size, not a shrunk default", async () => {
    const css = await compileUtilities(["text-sm"]);
    expect(declarationsOf(css, "text-sm")).toContain("font-size: var(--fs-chrome);");
  });

  it("compiles text-base to prose and the named steps to their own tokens", async () => {
    const css = await compileUtilities(["text-base", "text-eyebrow", "text-stat", "text-title"]);
    expect(declarationsOf(css, "text-base")).toContain("font-size: var(--fs-prose);");
    expect(declarationsOf(css, "text-eyebrow")).toContain("font-size: var(--fs-eyebrow);");
    expect(declarationsOf(css, "text-stat")).toContain("font-size: var(--fs-stat);");
    expect(declarationsOf(css, "text-title")).toContain("font-size: var(--fs-title);");
  });

  it("does not compile an off-scale stock size", async () => {
    const css = await compileUtilities(["text-lg", "text-xs", "text-9xl"]);
    expect(declarationsOf(css, "text-lg")).toBeNull();
    expect(declarationsOf(css, "text-xs")).toBeNull();
    expect(declarationsOf(css, "text-9xl")).toBeNull();
  });

  it("compiles leading-tight to this system's 1.05, not Tailwind's 1.25", async () => {
    const css = await compileUtilities(["leading-tight"]);
    expect(declarationsOf(css, "leading-tight")).toContain("line-height: var(--lh-tight);");
    expect(/--lh-tight:\s*1\.05\s*;/.test(css)).toBe(true);
  });
});

describe("motion is zero, without exception", () => {
  it("declares --animate-none as none", () => {
    expect(themeEntries("animate").get("--animate-none")).toBe("none");
  });

  it("compiles animate-none and nothing else", async () => {
    const css = await compileUtilities([
      "animate-none",
      "animate-spin",
      "animate-pulse",
      "animate-bounce",
      "animate-ping",
    ]);
    expect(declarationsOf(css, "animate-none")).toBe("animation: none;");
    for (const spinner of ["animate-spin", "animate-pulse", "animate-bounce", "animate-ping"]) {
      expect(declarationsOf(css, spinner)).toBeNull();
    }
  });

  it("emits no keyframes at all", async () => {
    const css = await compileUtilities(["animate-none", "animate-spin"]);
    expect(css).not.toContain("@keyframes");
  });

  it("compiles no easing function, because nothing eases", async () => {
    const css = await compileUtilities(["ease-in", "ease-out", "ease-in-out"]);
    expect(declarationsOf(css, "ease-in")).toBeNull();
    expect(declarationsOf(css, "ease-out")).toBeNull();
    expect(declarationsOf(css, "ease-in-out")).toBeNull();
  });
});

describe("the closed state vocabulary", () => {
  const vocabulary = [
    ["pinned", "[data-pinned]"],
    ["conflict", "[data-conflict]"],
    ["selected", "[data-selected]"],
    ["proposal", "[data-proposal]"],
    ["split", "[data-split]"],
    ["frame", '[data-origin="frame"]'],
    ["anchor", '[data-origin="anchor"]'],
    ["current", "[data-current]"],
    ["at-risk", "[data-at-risk]"],
    ["overdue", "[data-overdue]"],
    ["unconfirmed", "[data-unconfirmed]"],
    ["collecting", "[data-collecting]"],
  ] as const;

  it.each(vocabulary)("%s selects on its own attribute", async (variant, attribute) => {
    const css = await compileUtilities([`${variant}:bg-paper`]);
    expect(css).toContain(`${attribute} {`);
  });

  it.each([
    ["dragging", "[data-dragging]"],
    ["compact", "[data-compact]"],
    ["panel-open", '[data-panel="open"]'],
  ])("%s selects on an ancestor", async (variant, attribute) => {
    const css = await compileUtilities([`${variant}:bg-paper`]);
    expect(css).toContain(attribute);
  });

  it("has no variant a component could invent instead", async () => {
    const css = await compileUtilities(["hovered:bg-paper", "busy:bg-paper"]);
    expect(declarationsOf(css, "hovered:bg-paper")).toBeNull();
    expect(declarationsOf(css, "busy:bg-paper")).toBeNull();
  });
});

describe("the breakpoint namespace", () => {
  it("compiles no stock breakpoint, because none of them means anything to the width policy", async () => {
    const css = await compileUtilities(["sm:hidden", "lg:hidden", "2xl:hidden"]);
    expect(css).not.toContain("@media");
  });

  /* The two literals are the one place this file duplicates a token's value, because a media query
   * cannot read a custom property. These assertions are what make the duplicate incapable of
   * drifting: they read the token out of layout.css and require the theme's literal to equal it. */
  it.each([
    ["--breakpoint-wide", "--bp-wide"],
    ["--breakpoint-narrow", "--bp-compact"],
  ])("%s equals the %s token it mirrors", async (themeKey, tokenName) => {
    const layout = await readFile(path.join(srcDir, "tokens", "layout.css"), "utf8");
    const token = new RegExp(`${tokenName}:\\s*([^;]+);`).exec(layout);
    if (token === null) throw new Error(`layout.css declares no ${tokenName}`);

    expect(themeEntries("breakpoint").get(themeKey)).toBe(token[1].trim());
  });

  it("produces a real media query from each, evaluated rather than referencing a variable", async () => {
    const css = await compileUtilities(["wide:hidden", "narrow:hidden"]);

    expect(css).toContain("@media (width >= 1536px)");
    expect(css).toContain("@media (width >= 1280px)");
    expect(css).not.toMatch(/@media[^{]*var\(/);
  });

  it("does not name the lower threshold `compact`, which the state vocabulary owns", async () => {
    const css = await compileUtilities(["compact:text-sm"]);

    // `compact:` must still be the data-attribute variant, not a viewport query.
    expect(css).toContain("[data-compact]");
    expect(css).not.toMatch(/@media[^{]*\{\s*\.compact/);
  });
});

/* THE CONTENT SCAN, which is a correctness rule and not a performance one.
 *
 * Tailwind v4 detects sources across the whole project by default, so the `__fixtures__` files that
 * exist to prove a utility is BANNED were compiled into the bundle, and so were the tests and the
 * comments that merely NAME one: Tailwind's extractor reads every string in a scanned file, while the
 * markup scan blanks comments, reads only class strings, and ignores `__fixtures__`. Two input sets,
 * kept in step by hand, and the artifact was the thing nobody read. `dist` shipped a blurred shadow,
 * a rotate, a blur and a backdrop filter, and the last of them came from the prose in this very
 * comment, one word of which was the whole candidate.
 *
 * The scan is declared and narrowed now, and a check reads the built stylesheet rather than trusting
 * the narrowing. These tests fail if either half is dropped. */
describe("the content scan", () => {
  it("is declared rather than inferred, so a fixture cannot reach the bundle", () => {
    expect(themeSource).toContain('@import "tailwindcss" source(none)');
    expect(themeSource).toContain('@source "./**/*.{ts,tsx}"');
  });

  it("covers the application, so a real utility still compiles", async () => {
    const css = await compileUtilities(["bg-paper", "text-ink", "w-sidebar"]);

    expect(css).toContain("background-color");
    expect(css).toContain("color");
    expect(css).toContain("width");
  });
});
