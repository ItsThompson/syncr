/* THE DRAG HAS ONE DEGREE OF FREEDOM, AND THE TWO SURFACES THAT SETTLE THAT ARE CROSSED HERE.
 *
 * `useDiscreteDrag.ts` states the refusal as a decision and cites two surfaces for it: the design language's keyboard
 * gloss, and the drag table in its week-grid section. A citation nothing checks is a sentence that goes stale under
 * the tree it describes, so both are read. The document must gloss `Shift+↑`/`Shift+↓` as the keyboard equivalent of
 * the drag, must list no horizontal pair, and must carry the table that states the refusal and answers what follows
 * from it; the tree must bind that vertical pair and no horizontal one. A change that binds `Shift+←` widens the
 * gesture the document calls the drag's equivalent, and it reddens here rather than passing quietly while the
 * document describes a product that no longer exists.
 *
 * THE PARITY PROMISE IS REFUSED IN WHICHEVER SHAPE IT ARRIVES, and the promise that stands is pinned by its own
 * bolded claim. Section Keyboard promises that the keyboard reaches every block at every tier, which is about which
 * blocks a reader can get to, not about parity with every pointer capability. Under a parity promise the absent
 * horizontal pair would be a defect instead of the decision it is. This document states every rule as a bolded lede,
 * so a parity claim arrives either as a clause beside the promise or as a paragraph of its own: refusing the words
 * across the whole section catches both, where an equality on one line catches only the first.
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

/** The promise that stands, as the document states a rule: a bolded lede. */
const REACH_PROMISE = "**The keyboard reaches every block at every tier.**";

/** The claim the promise is not, in the two wordings the section could arrive at it by. */
const PARITY_CLAIM = /reaches everything the pointer does|parity/;

/** Both members, so the reading is blind neither to a horizontal pair arriving nor to the vertical pair going. */
const SHIFTED_ARROWS = [
  "ArrowDown in frontend/src/routes/week/hooks/useWeekScreenInteraction.ts",
  "ArrowUp in frontend/src/routes/week/hooks/useWeekScreenInteraction.ts",
];

/** The lede the drag table sits under, which is where the refusal is stated rather than inferred. */
const REFUSAL = "**A drag has one degree of freedom, and it is the minute.**";

/** The head of the one table the refusal is answered in, which is how its rows are found. */
const DRAG_TABLE_HEAD = "| Question | Answer | Why |";

/** Whole, so a question that goes is as visible as one that arrives. */
const DRAG_QUESTIONS = [
  "Does a pointer over another column retarget the drag?",
  "What does a drag across a week boundary mean?",
  "Does the keyboard get a horizontal equivalent?",
];

const ARROW_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
/** A keys cell naming a shifted arrow, spelt as a glyph or in words, because either would be a horizontal pair. */
const SHIFTED_ARROW_CELL = /Shift\+(?:[↑↓←→]|(?:Arrow)?(?:Up|Down|Left|Right)\b)/;

/** One section of the design language, from its own heading to the next one at that level. */
async function sectionOf(heading: string): Promise<string> {
  const doc = await readFile(path.join(repoRoot, "docs", "DESIGN-LANGUAGE.md"), "utf8");
  const section = doc.split(/^## /m).find((part) => part.startsWith(`${heading}\n`));
  if (section === undefined) throw new Error(`the design language has no ${heading} section`);
  return section;
}

/** The rows of the one table a section introduces with `head`, as their cells. */
function rowsUnder(section: string, head: string): string[][] {
  const lines = section.split("\n");
  const headAt = lines.indexOf(head);
  if (headAt === -1) throw new Error(`the section carries no table under ${head}`);
  const rows: string[][] = [];
  for (const line of lines.slice(headAt + 2)) {
    if (!line.startsWith("|")) break;
    rows.push(
      line
        .split("|")
        .slice(1, -1)
        .map((cell) => cell.trim()),
    );
  }
  return rows;
}

describe("the drag's keyboard equivalent, as the design language states it", () => {
  it("is the vertical pair the design language glosses, and it lists no horizontal pair", async () => {
    const rows = (await sectionOf("Keyboard"))
      .split("\n")
      .filter((line) => line.startsWith("|") && SHIFTED_ARROW_CELL.test(line));

    expect(rows).toEqual([EQUIVALENT_ROW]);
  });

  it("promises reach rather than parity, in whichever shape a parity claim would arrive", async () => {
    const section = await sectionOf("Keyboard");

    expect(section).toContain(REACH_PROMISE);
    expect(section.split("\n").filter((line) => PARITY_CLAIM.test(line))).toEqual([]);
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

/* THE OTHER SURFACE THE HEADER CITES. The table is this ticket's whole deliverable to a reader of the document, and
 * the header points at it, so deleting or gutting it is a failure here rather than a silence. */
describe("the drag table the header points at", () => {
  it("states the refusal and answers all three of the questions it raises", async () => {
    const section = await sectionOf("The week grid");

    expect(section).toContain(REFUSAL);
    expect(rowsUnder(section, DRAG_TABLE_HEAD).map((cells) => cells[0])).toEqual(DRAG_QUESTIONS);
  });
});
