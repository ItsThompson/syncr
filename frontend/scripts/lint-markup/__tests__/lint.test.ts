import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { appSourceDir } from "../../lib/paths.ts";
import { lintMarkup } from "../lint.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string): string => path.join(here, "..", "__fixtures__", name);
const themeFile = path.join(appSourceDir, "theme.css");

async function lint(names: string[], kitDir = path.join(here, "..", "__fixtures__", "kit")) {
  return lintMarkup({ sourceFiles: names.map(fixture), themeFile, kitDir });
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
    expect(outcome.notes[1]).toContain("data-current");
  });
});

describe("the markup rules", () => {
  it("catches every violation in one file", async () => {
    const outcome = await lint(["offender.tsx"]);
    expect(checksOf(outcome.findings).toSorted()).toEqual([
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

  it("reaches a utility hidden in a variant map", async () => {
    const outcome = await lint(["variants.tsx"]);
    expect(checksOf(outcome.findings).toSorted()).toEqual([
      "motion-is-zero",
      "no-radius-outside-the-kit",
    ]);
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

  it("catches all seven shapes and nothing else", async () => {
    const outcome = await lint(["compiling.tsx"]);

    expect(outcome.findings).toHaveLength(8);
    expect(checksOf(outcome.findings).toSorted()).toEqual([
      "motion-is-zero",
      "no-arbitrary-property",
    ]);
  });
});

/* THE INLINE STYLE PROP, which stylelint never sees. Only the absolutes are refused: a computed
 * length is how the week grid has to work, and a custom property is how an Area's ink is passed. */
describe("an inline style prop", () => {
  it("refuses a raw colour, a blurred shadow and a transition", async () => {
    const outcome = await lint(["inline-style.tsx"]);
    const style = outcome.findings
      .filter((finding) => finding.check === "no-raw-value-in-style")
      .map((finding) => finding.message);

    expect(style.some((message) => message.includes("a raw colour literal"))).toBe(true);
    expect(style.some((message) => message.includes("shadow other than --shadow-hard"))).toBe(true);
    expect(style.some((message) => message.includes("a transition"))).toBe(true);
  });

  it("permits a computed length and a custom property, which the grid and the chips need", async () => {
    const outcome = await lint(["inline-style.tsx"]);
    const lines = outcome.findings
      .filter((finding) => finding.check === "no-raw-value-in-style")
      .map((finding) => finding.line);

    // Every finding is on the first element; the computed one produces none.
    expect([...new Set(lines)]).toEqual([10]);
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
      themeFile,
      kitDir: path.join(here, "..", "__fixtures__"),
    });
    expect(checksOf(outcome.findings)).toEqual(["motion-is-zero"]);
  });

  it("permits rounded-full on an allowlisted circle", async () => {
    const outcome = await lint(["AreaChip.tsx"]);
    expect(outcome.findings).toEqual([]);
  });

  it("refuses rounded-full anywhere else, even inside the kit", async () => {
    const outcome = await lintMarkup({
      sourceFiles: [fixture("Panel.tsx")],
      themeFile,
      kitDir: path.join(here, "..", "__fixtures__"),
    });
    expect(checksOf(outcome.findings)).toEqual(["circle-allowlist"]);
    expect(outcome.findings[0].message).toContain("closed at those four");
  });
});
