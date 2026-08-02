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
    const arbitrary = outcome.findings.filter(
      (finding) => finding.check === "no-arbitrary-value",
    );
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

  it("reaches a utility hidden in a variant map", async () => {
    const outcome = await lint(["variants.tsx"]);
    expect(checksOf(outcome.findings).toSorted()).toEqual([
      "motion-is-zero",
      "no-radius-outside-the-kit",
    ]);
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
