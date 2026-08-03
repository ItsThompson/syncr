import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { validateTokenLayer } from "../validate.ts";

const fixtures = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "__fixtures__");
const fixture = (name: string): string => path.join(fixtures, name);

const cleanEntry = fixture("clean.css");

const onDisk = async (candidate: string): Promise<boolean> => {
  try {
    return (await stat(candidate)).isFile();
  } catch {
    return false;
  }
};

async function validate(
  tokenFiles: string[],
  sheetFiles: string[] = [],
  consumerFiles: string[] = [],
) {
  return validateTokenLayer({
    tokenFiles,
    consumerFiles,
    moduleFiles: [...tokenFiles, ...consumerFiles],
    exists: onDisk,
    tokenEntry: cleanEntry,
    sheetFiles,
  });
}

const checksOf = (findings: readonly { check: string }[]): string[] =>
  findings.map((finding) => finding.check);

describe("the clean layer", () => {
  it("passes every check", async () => {
    const outcome = await validate([cleanEntry], [fixture("sheet-ok.html")]);
    expect(outcome.findings).toEqual([]);
  });

  it("reports the caller-provided contract rather than hiding it", async () => {
    const outcome = await validate([cleanEntry]);
    expect(outcome.notes).toContain("caller-provided by contract: --hatch-ink");
  });

  it("counts the sheet references it could not resolve statically", async () => {
    const outcome = await validate([cleanEntry], [fixture("sheet-ok.html")]);
    expect(outcome.notes).toContain(
      "1 var() reference(s) in the sheets are assembled at runtime and are not statically resolvable",
    );
  });
});

describe("a prose paragraph left outside a comment pair", () => {
  it("fails, because this is the incident the check exists for", async () => {
    const outcome = await validate([fixture("prose-outside-comment.css")]);
    expect(outcome.findings.length).toBeGreaterThan(0);
  });

  it("names both the broken comment and the prose it turned into a statement", async () => {
    const outcome = await validate([fixture("prose-outside-comment.css")]);
    expect(checksOf(outcome.findings)).toEqual(
      expect.arrayContaining(["comment-balance", "root-statement"]),
    );
  });

  it("points at the line the closer sits on, not at the file", async () => {
    const outcome = await validate([fixture("prose-outside-comment.css")]);
    const balance = outcome.findings.find((finding) => finding.check === "comment-balance");
    expect(balance?.line).toBe(12);
  });

  it("quotes the prose so the reader can find it", async () => {
    const outcome = await validate([fixture("prose-outside-comment.css")]);
    const statement = outcome.findings.find((finding) => finding.check === "root-statement");
    expect(statement?.message).toContain("THE LABEL TIER LADDER");
  });
});

describe("an unterminated comment", () => {
  it("is reported, and the declarations it swallows are not counted as declared", async () => {
    const outcome = await validate([fixture("unterminated-comment.css")]);
    expect(checksOf(outcome.findings)).toEqual(["comment-balance"]);
    expect(outcome.notes[0]).toContain("0 declared propert(ies)");
  });
});

describe("a duplicate property", () => {
  it("is reported with the line of the declaration it overrides", async () => {
    const outcome = await validate([fixture("duplicate-property.css")]);
    expect(checksOf(outcome.findings)).toEqual(["duplicate-property"]);
    expect(outcome.findings[0].message).toContain("--h-control is already declared on line 5");
  });
});

describe("a dangling var() reference", () => {
  it("is reported in a token file", async () => {
    const outcome = await validate([fixture("dangling-var.css")]);
    expect(checksOf(outcome.findings)).toEqual(["dangling-reference"]);
    expect(outcome.findings[0].message).toContain("var(--ink-deepest)");
  });

  it("resolves across files, because the layer is one cascade", async () => {
    const outcome = await validate([cleanEntry, fixture("dangling-var.css")]);
    const dangling = outcome.findings.filter((finding) => finding.check === "dangling-reference");
    expect(dangling).toHaveLength(1);
  });
});

describe("a reference sheet", () => {
  it("fails when a token it reads was renamed", async () => {
    const outcome = await validate([cleanEntry], [fixture("sheet-drifted.html")]);
    expect(checksOf(outcome.findings)).toEqual(
      expect.arrayContaining(["dangling-sheet-reference"]),
    );
  });

  it("fails when its link to the token entry point does not resolve", async () => {
    const outcome = await validate([cleanEntry], [fixture("sheet-drifted.html")]);
    const links = outcome.findings.filter((finding) => finding.check === "stylesheet-reference");
    expect(links.map((finding) => finding.message)).toEqual([
      'href="./moved-tokens.css" does not resolve.',
      "links no stylesheet resolving to frontend/scripts/validate-tokens/__fixtures__/clean.css, " +
        "so it can drift from the build.",
    ]);
  });
});
