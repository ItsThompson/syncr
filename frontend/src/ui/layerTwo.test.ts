/* THE REVIEW CHECKLIST'S FIFTH QUESTION, ASKED OF THE TREE RATHER THAN OF A REVIEWER.
 *
 * "Did this component leave a layer 1 token behind that should have moved to layer 2 with it?" Section 14 names
 * three groups of tokens that sat in the token layer while no component existed to own them, and calls each move a
 * rename of location rather than of value. A promotion that half happened is the failure worth catching: the value
 * declared in both places drifts, and the value declared in neither resolves to nothing, which is the silent total
 * failure the token validator exists for.
 *
 * SO BOTH HALVES ARE ASSERTED. Each token is declared by the component that owns it, and by no file in the token
 * layer. The pairing of group to owner is section 14's own table, which is the one thing here that is written down
 * rather than derived: it is a DECISION about which component owns a value, and there is nowhere else to read it
 * from. What is derived is every consequence of it, so a token that moved to the wrong component, or moved and left
 * a copy behind, fails.
 *
 * THE OTHER SIX QUESTIONS ARE ANSWERED ELSEWHERE, each by a mechanism over the whole kit rather than per component:
 * the closed state vocabulary by `lint:markup`, the contrast ratios by the committed ledger, the combinations by
 * `stateCombinations.test.tsx`, tokens-rather-than-values and the forced-colors casualties by each layer's own
 * `layerRules` test, and the provability of a comment's claim by whether a script produced the figure it states.
 * `docs/design/audit-record.md` records which mechanism answers which question. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { appSourceDir, tokenDir } from "../../scripts/lib/paths.ts";

/** Section 14's promotion table: the tokens each group holds, and the component sheet that owns them. */
const PROMOTED: readonly { readonly owner: string; readonly tokens: readonly string[] }[] = [
  {
    owner: "domain/week-grid/tokens.css",
    tokens: [
      "--visible-hours",
      "--grid-h",
      "--px-per-min",
      "--axis-w",
      "--day-header-h",
      "--grid-major",
      "--grid-minor",
      "--block-h-label",
      "--block-h-compact",
      "--block-h-sliver",
      "--block-pad-x",
      "--block-pad-t",
      "--block-pad-b",
      "--overlap-max-split",
      "--overlap-indent",
    ],
  },
  {
    owner: "domain/verdict-panel/tokens.css",
    tokens: ["--verdict-h", "--strip-h"],
  },
  {
    owner: "domain/reason-rows/tokens.css",
    tokens: ["--clause-label-w"],
  },
];

/** Every custom property a stylesheet declares. */
async function declaredIn(file: string): Promise<Set<string>> {
  const declared = new Set<string>();
  parse(await readFile(file, "utf8")).walkDecls((declaration) => {
    if (declaration.prop.startsWith("--")) declared.add(declaration.prop);
  });
  return declared;
}

/** Every custom property the token layer declares, across its four files. */
async function declaredInLayerOne(): Promise<Set<string>> {
  const entries = await readdir(tokenDir, { withFileTypes: true });
  const files = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".css"))
    .map((entry) => path.join(tokenDir, entry.name));
  const declared = new Set<string>();
  const perFile = await Promise.all(files.map(async (file) => declaredIn(file)));
  for (const tokens of perFile) {
    for (const token of tokens) declared.add(token);
  }
  return declared;
}

describe("the tokens section 14 promotes to layer 2", () => {
  it.each(PROMOTED)(
    "are declared by $owner, which is the component that owns them",
    async (group) => {
      const declared = await declaredIn(path.join(appSourceDir, "ui", group.owner));

      expect([...group.tokens].filter((token) => !declared.has(token))).toEqual([]);
    },
  );

  it("are declared by no file in the token layer, so no copy was left behind", async () => {
    const layerOne = await declaredInLayerOne();
    const promoted = PROMOTED.flatMap((group) => group.tokens);

    expect(promoted.filter((token) => layerOne.has(token))).toEqual([]);
  });

  /* The token layer still says WHERE each group went, which is what makes the promotion readable from the place a
   * reader would look for the value. A pointer is not a second copy: it names a file rather than a figure. */
  it("are pointed at from the token layer, so a reader looking for the value finds its home", async () => {
    const layout = await readFile(path.join(tokenDir, "layout.css"), "utf8");

    for (const group of PROMOTED) {
      expect(layout).toContain(group.owner.replace("domain/", "ui/domain/"));
    }
  });

  /* The reading's own control. Layer 1 declares plenty, and a promotion check that passed because it was reading an
   * empty set would pass whatever the tree did. */
  it("is checked against a token layer that declares the rest of the system", async () => {
    const layerOne = await declaredInLayerOne();

    expect(layerOne.size).toBeGreaterThan(100);
    expect(layerOne.has("--paper")).toBe(true);
    expect(layerOne.has("--duration")).toBe(true);
  });
});
