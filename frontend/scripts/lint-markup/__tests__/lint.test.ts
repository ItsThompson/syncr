import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { appSourceDir } from "../../lib/paths.ts";
import { emittedDeclarationsFor } from "../../lib/tailwind.ts";
import { CIRCLE_ALLOWLIST, isCircleAllowed } from "../circles.ts";
import { refusedByEmittedCss } from "../emitted.ts";
import { lintMarkup } from "../lint.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string): string => path.join(here, "..", "__fixtures__", name);
const themeFile = path.join(appSourceDir, "theme.css");

const sourceRoot = path.join(here, "..", "..", "..", "src");

async function lint(names: string[], kitDir = path.join(here, "..", "__fixtures__", "kit")) {
  return lintMarkup({
    sourceFiles: names.map(fixture),
    styleSheets: [],
    themeFile,
    kitDir,
    sourceRoot,
  });
}

async function lintStyleSheets(names: string[]) {
  return lintMarkup({
    sourceFiles: [],
    styleSheets: names.map(fixture),
    themeFile,
    kitDir: path.join(here, "..", "__fixtures__"),
    sourceRoot,
  });
}

const checksOf = (findings: readonly { check: string }[]): string[] => [
  ...new Set(findings.map((finding) => finding.check)),
];

describe("on-brand markup", () => {
  it("produces no finding", async () => {
    const outcome = await lint(["clean.tsx"]);
    expect(outcome.findings).toEqual([]);
  });

  /* The fixture's own comment names an invented attribute and an arbitrary value. A check that fired
   * on the prose documenting it would be one people learn to route around. */
  it("reads code rather than prose, so a comment cannot trip a rule", async () => {
    const source = await readFile(fixture("clean.tsx"), "utf8");

    expect(source).toContain("data-busy");
    expect(source).toContain("w-[13px]");
    expect((await lint(["clean.tsx"])).findings).toEqual([]);
  });

  it("reports the vocabulary it read, so a silent empty set is visible", async () => {
    const outcome = await lint(["clean.tsx"]);
    expect(outcome.notes.some((note) => note.includes("data-current"))).toBe(true);
  });

  it("reports how many utilities it compiled, so a silent zero is visible", async () => {
    const outcome = await lint(["clean.tsx"]);
    expect(outcome.notes.some((note) => /[1-9]\d* distinct utilit/.test(note))).toBe(true);
  });
});

describe("the markup rules", () => {
  it("catches every violation in one file", async () => {
    const outcome = await lint(["offender.tsx"]);
    expect(checksOf(outcome.findings).toSorted()).toEqual([
      "banned-emitted-css",
      "closed-state-vocabulary",
      "motion-is-zero",
      "no-arbitrary-value",
      "no-layer-zero-token",
      "no-radius-outside-the-kit",
    ]);
  });

  it("names the arbitrary value and points at it", async () => {
    const outcome = await lint(["offender.tsx"]);
    const arbitrary = outcome.findings.filter((finding) => finding.check === "no-arbitrary-value");
    expect(arbitrary.map((finding) => finding.message)).toEqual([
      "w-[13px] is an arbitrary value. A value not on the scale becomes a token first.",
      "text-[11px] is an arbitrary value. A value not on the scale becomes a token first.",
    ]);
    expect(arbitrary[0].line).toBe(5);
  });

  it("tells the author how to make a new state lintable", async () => {
    const outcome = await lint(["offender.tsx"]);
    const vocabulary = outcome.findings.find(
      (finding) => finding.check === "closed-state-vocabulary",
    );
    expect(vocabulary?.message).toContain("data-busy");
    expect(vocabulary?.message).toContain("@custom-variant");
  });

  it("catches a valueless boolean attribute, which is how the state is usually written", async () => {
    const outcome = await lint(["offender.tsx"]);
    const invented = outcome.findings
      .filter((finding) => finding.check === "closed-state-vocabulary")
      .map((finding) => finding.message);

    expect(invented.some((message) => message.startsWith("data-bare"))).toBe(true);
  });

  it("catches an attribute spread onto an element rather than written on it", async () => {
    const outcome = await lint(["offender.tsx"]);
    const invented = outcome.findings
      .filter((finding) => finding.check === "closed-state-vocabulary")
      .map((finding) => finding.message);

    expect(invented.some((message) => message.startsWith("data-spread"))).toBe(true);
  });

  /* A TEST IS EXEMPT FROM THIS ONE RULE AND FROM NO OTHER. A test asserts what a component RENDERS, and a Radix
   * control renders `data-state` and `data-highlighted` whether or not the kit's vocabulary names them: a suite
   * that could not write those strings could not check the kit's own state channels. The rule's purpose is that a
   * component cannot invent an attribute, and a component file is still read, which the next case proves. */
  it("leaves a test file's assertions about a library's attributes alone", async () => {
    const outcome = await lint(["vocabulary.test.tsx"]);

    expect(checksOf(outcome.findings)).toEqual([]);
  });

  it("still catches the same attribute in a component, so the exemption is the file and not the name", async () => {
    const outcome = await lint(["offender.tsx"]);

    expect(checksOf(outcome.findings)).toContain("closed-state-vocabulary");
  });

  it("reaches a utility hidden in a variant map", async () => {
    const outcome = await lint(["variants.tsx"]);
    expect(checksOf(outcome.findings).toSorted()).toEqual([
      "banned-emitted-css",
      "motion-is-zero",
      "no-radius-outside-the-kit",
    ]);
  });
});

/* A CLASS LIST HAS TO SIT WHERE THE SCAN CAN READ IT.
 *
 * Four rules take a class list as their input, and a list hoisted into a module constant is read by none of
 * them: the same string that produces three findings at the attribute produced an exit code of 0, and the
 * utility count fell from 129 to 128 as the violation was added. The emitted-CSS gate catches the motion half
 * from the artifact; nothing else reads the circle allowlist, so this rule is what keeps it enforceable. */
describe("an unreadable class list", () => {
  async function readabilityFindings() {
    const outcome = await lint(["hoisted-class-list.tsx"]);
    return outcome.findings.filter((finding) => finding.check === "readable-class-list");
  }

  it("is refused when the list is a module constant", async () => {
    const hoisted = (await readabilityFindings()).find((finding) => finding.line === 21);

    expect(hoisted?.message).toContain("className={HOISTED}");
    expect(hoisted?.message).toContain("cannot read");
  });

  it("is refused when a template literal interpolates part of it", async () => {
    const interpolated = (await readabilityFindings()).find((finding) => finding.line === 22);

    expect(interpolated?.message).toContain("interpolates part of its class list");
  });

  /* THE BRANCH THAT HID A CIRCLE. A literal in one branch kept the expression legal, and `rounded-full` in the
   * constant behind the other reached an element with nothing reading it: `lint:bundle` cannot judge a
   * `border-radius: 50%`, which is legal CSS for the four allowlisted files, so this scan is the only reader the
   * circle allowlist has. */
  it("is refused when a ternary branch is not a literal, naming the branch", async () => {
    const branch = (await readabilityFindings()).find((finding) => finding.line === 25);

    expect(branch?.message).toContain("chooses a branch");
    expect(branch?.message).toContain("HOISTED");
  });

  it("reads a nested ternary's branches, not the conditions between them", async () => {
    const nested = (await readabilityFindings()).find((finding) => finding.line === 26);

    // The branch it names is the hidden VALUE, `EXTRA`, rather than the `rank === "lead"` that chose it.
    expect(nested?.message).toContain("chooses a branch, `EXTRA`");
  });

  it("leaves a variant map's own call alone, which is the shape the kit is written in", async () => {
    expect((await readabilityFindings()).map((finding) => finding.line)).toEqual([21, 22, 25, 26]);
  });

  it("leaves a ternary inside a variant map's argument alone", async () => {
    expect((await readabilityFindings()).some((finding) => finding.line === 27)).toBe(false);
  });

  /* The hoisted constant carries `rounded-full` and `transition-all`. Refusing the attribute is the only
   * reason either is reported at all: the class-list rules never see the string. */
  it("is the whole of what the file reports, because the hidden utilities stay hidden", async () => {
    const outcome = await lint(["hoisted-class-list.tsx"]);

    expect(checksOf(outcome.findings)).toEqual(["readable-class-list"]);
  });

  it("is not asked of a test file, which asserts about markup rather than drawing it", async () => {
    const outcome = await lint(["vocabulary.test.tsx"]);

    expect(checksOf(outcome.findings)).toEqual([]);
  });
});

/* THE SHAPES THAT COMPILED. Each one produced real CSS through Tailwind's own compiler while every
 * check was green, and four of them reach a prohibition the design language states without exception.
 * The theme cannot fence any of them: `[prop:value]` is not namespace-driven, so clearing
 * `--color-*` and `--animate-*` does not touch it. */
describe("Tailwind v4 shapes the theme cannot fence", () => {
  it("catches the arbitrary-property form, which no theme namespace covers", async () => {
    const outcome = await lint(["compiling.tsx"]);
    const properties = outcome.findings.filter(
      (finding) => finding.check === "no-arbitrary-property",
    );

    expect(properties.map((finding) => finding.message.split(" ")[0])).toEqual([
      "[color:red]",
      "[background:#ff0000]",
      "[box-shadow:0_0_8px_red]",
      "[--my-var:3px]",
      "[color:red]",
    ]);
  });

  it("catches it behind a variant prefix, which the old tokenizer destroyed", async () => {
    const outcome = await lint(["compiling.tsx"]);

    // `md:[color:red]` used to become `red]` before any rule ran.
    expect(
      outcome.findings.filter((finding) => finding.check === "no-arbitrary-property"),
    ).toHaveLength(5);
  });

  it.each(["-translate-x-2", "-rotate-3", "-skew-y-2"])(
    "catches the negative transform utility %s",
    async (utility) => {
      const outcome = await lint(["compiling.tsx"]);
      const motion = outcome.findings
        .filter((finding) => finding.check === "motion-is-zero")
        .map((finding) => finding.message);

      expect(motion.some((message) => message.startsWith(utility))).toBe(true);
    },
  );

  it("catches all seven shapes, by pattern and by emitted CSS", async () => {
    const outcome = await lint(["compiling.tsx"]);

    expect(checksOf(outcome.findings).toSorted()).toEqual([
      "banned-emitted-css",
      "motion-is-zero",
      "no-arbitrary-property",
    ]);
    // Eight by pattern, and the four that actually compile are refused a second time by what they
    // emit: the three negative transforms and the arbitrary box-shadow.
    expect(
      outcome.findings.filter((finding) => finding.check === "banned-emitted-css"),
    ).toHaveLength(4);
    expect(outcome.findings).toHaveLength(12);
  });
});

/* THE INLINE STYLE PROP, which stylelint never sees. Only the absolutes are refused: a computed
 * length is how the week grid has to work, and a custom property is how an Area's ink is passed.
 *
 * The camelCase cases below are review iteration 5's finding, and they are the one defect in that
 * round that was applied CSS rather than dead bytes: a rendered blur on the real sidebar, a
 * `will-change` this repository's own stylelint list bans, and `outline: none` on a keyboard-first
 * product. Each passed all seven checks. */
describe("an inline style prop", () => {
  async function styleFindings() {
    const outcome = await lint(["inline-style.tsx"]);
    return outcome.findings.filter((finding) => finding.check.endsWith("-in-style"));
  }

  it("refuses a raw colour literal, whatever property carries it", async () => {
    const messages = (await styleFindings()).map((finding) => finding.message);

    expect(messages.some((message) => message.includes("a raw colour literal"))).toBe(true);
    expect(messages.some((message) => message.includes("a named colour"))).toBe(true);
  });

  it.each([
    ["boxShadow", "box-shadow"],
    ["transition", "transition"],
    ["backdropFilter", "backdrop-filter"],
    ["willChange", "will-change"],
    ["WebkitFilter", "-webkit-filter"],
    ["outline", "outline"],
  ])("refuses %s, and names it as %s", async (key, property) => {
    const refusal = (await styleFindings()).find((finding) => finding.message.includes(`${key},`));

    expect(refusal?.check).toBe("no-banned-property-in-style");
    expect(refusal?.message).toContain(property);
  });

  it("refuses a radius, which defeats the radius rule and the circle allowlist together", async () => {
    const radii = (await styleFindings()).filter(
      (finding) => finding.check === "no-radius-in-style",
    );

    expect(radii.map((finding) => finding.line)).toEqual([19, 20]);
    expect(radii[0].message).toContain('borderRadius: "8px"');
    expect(radii[0].message).toContain("Radius is zero");
  });

  it("permits a computed length, a custom property and a square radius", async () => {
    const lines = (await styleFindings()).map((finding) => finding.line);

    // The computed element is line 17 and produces nothing. Every other element is a finding.
    expect([...new Set(lines)].toSorted((left, right) => (left ?? 0) - (right ?? 0))).toEqual([
      16, 18, 19, 20,
    ]);
  });

  it("says why, naming the rule rather than the mechanism", async () => {
    const outcome = await lint(["inline-style.tsx"]);
    const first = outcome.findings.find((finding) => finding.check === "no-raw-value-in-style");

    expect(first?.message).toContain("reads tokens rather than restating");
    expect(first?.message).toContain("A computed length is fine");
  });
});

describe("the radius rules", () => {
  it("permits rounded-* inside the kit", async () => {
    const outcome = await lintMarkup({
      sourceFiles: [fixture("variants.tsx")],
      styleSheets: [],
      themeFile,
      kitDir: path.join(here, "..", "__fixtures__"),
      sourceRoot,
    });
    expect(checksOf(outcome.findings).toSorted()).toEqual(["banned-emitted-css", "motion-is-zero"]);
  });

  it("permits rounded-full on an allowlisted circle", async () => {
    const outcome = await lint(["AreaChip.tsx"]);
    expect(outcome.findings).toEqual([]);
  });

  /* The allowlist is four ELEMENTS, not four directories. Matching a path substring allowed every
   * file under `Avatar/`, `AreaChip/` or `Radio/` a circle, and nothing tested it. */
  it("refuses a circle in a file merely sitting inside an allowlisted directory", async () => {
    const outcome = await lintMarkup({
      sourceFiles: [fixture(path.join("Avatar", "Banner.tsx"))],
      styleSheets: [],
      themeFile,
      kitDir: path.join(here, "..", "__fixtures__"),
      sourceRoot,
    });

    expect(checksOf(outcome.findings)).toEqual(["circle-allowlist"]);
  });

  it("holds four names, for the four elements the design language names", () => {
    expect([...CIRCLE_ALLOWLIST]).toHaveLength(4);
  });

  /* The allowlist is read by two rules now, the class-list one and the inline-style one, so the filename
   * match is asserted where it is written rather than through each of them. */
  it("reads an element's own file name, not a directory it happens to sit in", () => {
    expect(isCircleAllowed("/src/ui/domain/areas/AreaChip.tsx")).toBe(true);
    expect(isCircleAllowed("/src/ui/domain/areas/AreaChip/Banner.tsx")).toBe(false);
  });

  it("refuses rounded-full anywhere else, even inside the kit", async () => {
    const outcome = await lintMarkup({
      sourceFiles: [fixture("Panel.tsx")],
      styleSheets: [],
      themeFile,
      kitDir: path.join(here, "..", "__fixtures__"),
      sourceRoot,
    });
    expect(checksOf(outcome.findings)).toEqual(["circle-allowlist"]);
    expect(outcome.findings[0].message).toContain("closed at those four");
  });
});

/* THE VERDICT DERIVED FROM WHAT A UTILITY COMPILES TO, rather than from how it is spelled.
 *
 * Every shape below put a banned declaration into `dist` with all seven checks, tsc, prettier and
 * `vite build` green. The two arbitrary-value patterns were written around `[`, so Tailwind's paren
 * form was invisible; `MOTION_UTILITY` had no root for `delay-` or `will-change-`; and `@apply` in a
 * stylesheet was read by nothing, since the markup scan took .ts and .tsx while stylelint's rules are
 * declaration-based. */
describe("the emitted-CSS verdict", () => {
  it.each([
    ["blur-(--haze)", "print has no blur"],
    ["backdrop-blur-(--haze)", "print has no blur"],
    ["shadow-(--halo)", "the system has one shadow"],
    ["delay-300", "motion is zero, without exception"],
    ["will-change-transform", "motion is zero, without exception"],
  ])("refuses %s because %s", async (utility, reason) => {
    const outcome = await lint(["paren-forms.tsx"]);
    const emitted = outcome.findings
      .filter((finding) => finding.check === "banned-emitted-css")
      .map((finding) => finding.message);

    expect(emitted.some((message) => message.startsWith(utility))).toBe(true);
    expect(emitted.some((message) => message.startsWith(utility) && message.includes(reason))).toBe(
      true,
    );
  });

  /* `w-(--wide)` is `w-[13px]` in another spelling. No emitted declaration distinguishes it from
   * `w-sidebar`, since both emit `width: var(...)`, so the arbitrary-value rule is the only thing that
   * can refuse it. Both halves are load-bearing. */
  it.each(["w-(--wide)", "bg-(--tint)", "blur-(--haze)", "shadow-(--halo)"])(
    "refuses the paren form %s as an arbitrary value",
    async (utility) => {
      const outcome = await lint(["paren-forms.tsx"]);
      const arbitrary = outcome.findings
        .filter((finding) => finding.check === "no-arbitrary-value")
        .map((finding) => finding.message);

      expect(arbitrary.some((message) => message.startsWith(utility))).toBe(true);
    },
  );

  it("reaches @apply in a stylesheet, which every check used to miss", async () => {
    const outcome = await lintStyleSheets(["applied.css"]);
    const emitted = outcome.findings
      .filter((finding) => finding.check === "banned-emitted-css")
      .map((finding) => finding.message);

    expect(emitted.some((message) => message.startsWith("blur-(--haze)"))).toBe(true);
    expect(emitted.some((message) => message.startsWith("shadow-(--halo)"))).toBe(true);
    expect(emitted.some((message) => message.startsWith("transition-(--pace)"))).toBe(true);
    expect(emitted.some((message) => message.startsWith("delay-300"))).toBe(true);
  });

  it("points at the @apply that named the utility", async () => {
    const outcome = await lintStyleSheets(["applied.css"]);
    const first = outcome.findings.find((finding) => finding.check === "banned-emitted-css");

    expect(first?.line).toBe(9);
  });

  /* WHY BOTH MECHANISMS STAY. The theme CLEARS `--animate-*`, `--blur-*` and the stock shadow scale,
   * so `animate-spin` and `blur-sm` compile to nothing: the emitted-CSS verdict cannot see them and
   * only the pattern rule tells the author the class is dead. The reverse holds for `delay-300`, which
   * no pattern listed. Deleting either half loses real cases. */
  it("cannot see a utility the theme neutralised, which is why the pattern rule stays", async () => {
    const neutralised = await emittedDeclarationsFor(sourceRoot, [
      "animate-spin",
      "blur-sm",
      "shadow-lg",
      "ease-in",
    ]);

    for (const [, declarations] of neutralised) expect(declarations).toEqual([]);
    expect(refusedByEmittedCss(neutralised)).toEqual([]);
  });

  it("does see the compiling shapes no pattern listed, which is why it stays", async () => {
    const compiling = await emittedDeclarationsFor(sourceRoot, [
      "delay-300",
      "will-change-transform",
      "blur-(--haze)",
    ]);

    expect(
      refusedByEmittedCss(compiling)
        .map((verdict) => verdict.utility)
        .toSorted(),
    ).toEqual(["blur-(--haze)", "delay-300", "will-change-transform"]);
  });

  it("leaves the one legal animation and the one legal shadow alone", async () => {
    const legal = await emittedDeclarationsFor(sourceRoot, [
      "animate-none",
      "shadow-sm",
      "bg-paper",
    ]);
    expect(refusedByEmittedCss(legal)).toEqual([]);
  });
});
