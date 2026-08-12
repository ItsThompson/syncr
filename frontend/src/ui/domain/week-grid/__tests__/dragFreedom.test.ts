/* THE DRAG HAS ONE DEGREE OF FREEDOM, AND THE TWO SURFACES THAT SETTLE THAT ARE CROSSED HERE.
 *
 * `useDiscreteDrag.ts` states the refusal as a decision and cites the design language for it. A citation nothing
 * checks is a sentence that goes stale under the tree it describes, so both halves of the citation are read: the
 * document must still gloss `Shift+Up`/`Shift+Down` as the keyboard equivalent of the drag and still list no
 * horizontal pair, and the tree must still bind that vertical pair and no horizontal one. A change that binds
 * `Shift+Left` widens the gesture the document calls the drag's equivalent, and it reddens here rather than passing
 * quietly while the document describes a product that no longer exists.
 *
 * THE REACH PROMISE IS PINNED BY THE WHOLE LINE IT IS MADE IN, because a broader reading of it is available and
 * wrong. Section Keyboard promises that the keyboard reaches every block at every tier, which is about which blocks
 * a reader can get to, not about parity with every pointer capability. Under a parity promise the absent horizontal
 * pair would be a defect instead of the decision it is, and a clause added beside the promise is how that reading
 * arrives, which is why the assertion is an equality rather than a search for the sentence.
 *
 * WHAT THE BINDING CENSUS COVERS. `useKeyBinding` is the one mechanism in this tree that can require Shift, which
 * the last case measures rather than assumes; the drag's own window listener reads `Escape` alone, and a kit control
 * that answers an arrow inside itself answers it unshifted. So a `useKeyBinding` call is the whole population, read
 * through `scripts/lib/key-bindings.ts` so that this file and the shell's own check cannot read it two ways. A
 * shifted binding whose key names a constant that reader cannot resolve is a refusal rather than a pass, because an
 * unreadable spelling could be the very pair being refused. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { keyRegistrations, shippedSources } from "../../../../../scripts/lib/key-bindings.ts";
import { repoRoot } from "../../../../../scripts/lib/paths.ts";

/** The gloss the drag's header cites as its authority, in the document's own words. */
const EQUIVALENT_ROW =
  "| `Shift+↑` `Shift+↓` | move by 15 minutes and pin. the keyboard equivalent of the drag |";

/** The promise whole, so a clause added beside it is a failure rather than a still-passing substring. */
const REACH_PROMISE =
  "**The keyboard reaches every block at every tier.** `j` and `k` do not care how tall a block is, so the smallest block in the week is exactly as reachable as the largest. That matters more than the pointer path, because a 9.8px pointer target is genuinely small.";

/** Both members, so the reading is blind neither to a horizontal pair arriving nor to the vertical pair going. */
const SHIFTED_ARROWS = [
  "ArrowDown in frontend/src/routes/week/hooks/useWeekScreenInteraction.ts",
  "ArrowUp in frontend/src/routes/week/hooks/useWeekScreenInteraction.ts",
];

const ARROW_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
const SHIFTED_ARROW_CELL = /Shift\+[↑↓←→]/;

/** The design language's keyboard section, from its own heading to the next one. */
async function keyboardSection(): Promise<string> {
  const doc = await readFile(path.join(repoRoot, "docs", "DESIGN-LANGUAGE.md"), "utf8");
  const section = doc.split(/^## /m).find((part) => part.startsWith("Keyboard\n"));
  if (section === undefined) throw new Error("the design language has no Keyboard section");
  return section;
}

describe("the keyboard equivalent of the drag", () => {
  it("is the vertical pair the design language glosses, and it lists no horizontal pair", async () => {
    const rows = (await keyboardSection())
      .split("\n")
      .filter((line) => line.startsWith("|") && SHIFTED_ARROW_CELL.test(line));

    expect(rows).toEqual([EQUIVALENT_ROW]);
  });

  it("promises reach rather than parity, so the absent horizontal pair is a decision", async () => {
    const promise = (await keyboardSection())
      .split("\n")
      .find((line) => line.includes("keyboard reaches every block"));

    expect(promise).toBe(REACH_PROMISE);
  });

  it("is bound as that pair, and nothing in the tree binds a horizontal one", async () => {
    const shifted = (await keyRegistrations()).filter((registration) => registration.withShift);
    const arrows = shifted.flatMap((registration) =>
      registration.key !== null && ARROW_KEYS.has(registration.key)
        ? [`${registration.key} in ${path.relative(repoRoot, registration.file)}`]
        : [],
    );

    expect(arrows.toSorted()).toEqual(SHIFTED_ARROWS);
    /* A shifted key spelt as a constant the reader cannot resolve could be the pair being refused, so an unreadable
     * spelling fails the claim rather than dropping quietly out of it. */
    expect(shifted.filter((registration) => registration.key === null)).toEqual([]);
  });

  it("is registered through the one mechanism that reads Shift, which is what makes that pair the whole set", async () => {
    const readers = (await shippedSources())
      .filter(({ code }) => code.includes("shiftKey"))
      .map(({ file }) => path.relative(repoRoot, file));

    expect(readers).toEqual(["frontend/src/lib/keyboard/useKeyBinding.ts"]);
  });
});
