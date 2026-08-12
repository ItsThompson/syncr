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
  it("is reported in a token file, and offers the annotation as one of the two remedies", async () => {
    const outcome = await validate([fixture("dangling-var.css")]);
    expect(checksOf(outcome.findings)).toEqual(["dangling-reference"]);
    expect(outcome.findings[0].message).toBe(
      "var(--ink-deepest) resolves to nothing. Declare it, or annotate the contract with " +
        '"@caller-provided --ink-deepest" in a comment where the caller\'s formula is stated.',
    );
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

/* `docs/DESIGN-LANGUAGE.md`'s token architecture moves a component's geometry out of the token layer and beside
 * the component when that component is built, which changes where a value is declared and not the value. A check
 * that resolved a sheet's references against `tokens/` alone refused every such promotion, so the interim
 * location had become a rule. What keeps the sheet honest is the LINK: the value has to be on the same load the
 * check approved. */
describe("a token promoted out of the layer and beside its component", () => {
  const promoted = fixture("promoted-layer-2.css");

  it("resolves in a sheet that links the layer-2 sheet declaring it", async () => {
    const outcome = await validate([cleanEntry], [fixture("sheet-promoted.html")], [promoted]);

    expect(outcome.findings).toEqual([]);
  });

  it("counts the properties reached that way, so a silent zero shows", async () => {
    const outcome = await validate([cleanEntry], [fixture("sheet-promoted.html")], [promoted]);

    expect(outcome.notes).toContain(
      "  3 propert(ies) reached that way, which is where a promoted layer-2 token lives",
    );
  });

  it("dangles in a sheet that reads it without linking it", async () => {
    const outcome = await validate(
      [cleanEntry],
      [fixture("sheet-unlinked-promotion.html")],
      [promoted],
    );
    const dangling = outcome.findings.filter(
      (finding) => finding.check === "dangling-sheet-reference",
    );

    expect(dangling.map((finding) => finding.message)).toEqual([
      "var(--grid-h) resolves against none of the token files, the stylesheets this sheet links, " +
        "or its own declarations, so the sheet renders a missing value and still looks plausible.",
    ]);
  });
});

/* `@caller-provided` states that the element drawing with a property supplies its value. CSS
 * substitutes a `var()` against the element the declaration is written on, so the contract can hold
 * on an ordinary rule and cannot hold inside `:root`: there the reference reads the root element's
 * own value, which no caller can write. An annotation the layer resolves at `:root` therefore buys
 * nothing, in the layer, in a consumer, or in a sheet. */
describe("a @caller-provided contract the layer resolves itself", () => {
  const atRoot = fixture("caller-provided-at-root.css");
  const consumer = fixture("caller-provided-consumer.css");
  const drawnBySheet = fixture("sheet-caller-drawn.html");

  it("refuses each annotation, on the annotation, naming the site the layer resolves it at", async () => {
    const outcome = await validate([atRoot]);

    expect(
      outcome.findings.filter((finding) => finding.check === "caller-provided-refused"),
    ).toEqual([
      {
        file: atRoot,
        line: 10,
        column: 4,
        check: "caller-provided-refused",
        message:
          "@caller-provided --hatch-ink is refused. The token layer resolves var(--hatch-ink) " +
          "itself at frontend/scripts/validate-tokens/__fixtures__/" +
          "caller-provided-at-root.css:15:49, inside a :root block, where CSS substitutes it " +
          "against the root element, so no element below the root can supply it and the root is " +
          "not the element that draws. Declare --hatch-ink, or move the reference onto the rule " +
          "that paints.",
      },
      {
        file: atRoot,
        line: 11,
        column: 4,
        check: "caller-provided-refused",
        message:
          "@caller-provided --band-ink is refused. The token layer resolves var(--band-ink) " +
          "itself at frontend/scripts/validate-tokens/__fixtures__/" +
          "caller-provided-at-root.css:16:26, inside a :root block, where CSS substitutes it " +
          "against the root element, so no element below the root can supply it and the root is " +
          "not the element that draws. Declare --band-ink, or move the reference onto the rule " +
          "that paints.",
      },
    ]);
  });

  /* Two references to one contract, so the refusal is per annotation rather than per site: the
   * annotation is the defect and the dangling findings already point at every use. */
  it("reports the references the annotation had been suppressing", async () => {
    const outcome = await validate([atRoot]);
    const dangling = outcome.findings.filter((finding) => finding.check === "dangling-reference");

    expect(dangling.map((finding) => `${finding.line}:${finding.column}`)).toEqual([
      "15:49",
      "16:26",
      "17:51",
    ]);
    expect(dangling[0].message).toContain("var(--hatch-ink) resolves to nothing");
    expect(dangling[1].message).toContain("var(--band-ink) resolves to nothing");
    expect(dangling[2].message).toContain("var(--hatch-ink) resolves to nothing");
  });

  it("does not send the reader back to the annotation it just refused", async () => {
    const outcome = await validate([atRoot]);
    const dangling = outcome.findings.find((finding) => finding.check === "dangling-reference");

    expect(dangling?.message).toBe(
      "var(--hatch-ink) resolves to nothing. Declare it, or move the reference onto the rule that " +
        'paints. The "@caller-provided --hatch-ink" annotation cannot excuse it here.',
    );
  });

  it("stops naming it in the notes as a contract the layer keeps", async () => {
    const outcome = await validate([atRoot]);

    expect(outcome.notes.filter((note) => note.startsWith("caller-provided by contract"))).toEqual(
      [],
    );
  });

  it("leaves a consumer's reference dangling, wherever the layer resolved it", async () => {
    const outcome = await validate([cleanEntry, atRoot], [], [consumer]);

    expect(
      outcome.findings
        .filter((finding) => finding.file === consumer)
        .map((finding) => `${finding.check} ${finding.line}:${finding.column}`),
    ).toEqual(["dangling-reference 6:54"]);
  });

  it("leaves a reference sheet's reference dangling too", async () => {
    const outcome = await validate([cleanEntry, atRoot], [drawnBySheet]);

    expect(
      outcome.findings
        .filter((finding) => finding.file === drawnBySheet)
        .map((finding) => `${finding.check} ${finding.line}:${finding.column}`),
    ).toEqual(["dangling-sheet-reference 13:11"]);
  });
});

describe("a @caller-provided contract the drawing element can reach", () => {
  it("holds when the layer draws with it on a rule instead of inside :root", async () => {
    const outcome = await validate([fixture("caller-provided-in-a-rule.css")]);

    expect(outcome.findings).toEqual([]);
    expect(outcome.notes).toContain("caller-provided by contract: --hatch-ink");
  });

  it("holds for a consumer that draws with it", async () => {
    const outcome = await validate([cleanEntry], [], [fixture("caller-provided-consumer.css")]);

    expect(outcome.findings).toEqual([]);
  });

  it("holds for a reference sheet that draws with it and declares nothing itself", async () => {
    const outcome = await validate([cleanEntry], [fixture("sheet-caller-drawn.html")]);

    expect(outcome.findings).toEqual([]);
  });
});
