/* THE AUDIT'S VERDICT ON THE PALETTE: the rules composed, and the figures the run prints.
 *
 * The rules themselves are in `rules.ts`, one function each. What is left here is the resolution every rule shares
 * and the notes, and the notes matter as much as the findings: a check that silently passes cannot be told apart
 * from a check that stopped running, so every figure is printed whether the gate passes or fails.
 *
 * EVERY FIGURE IS COMPUTED FROM THE LEDGER THIS RUN READ. Two units meet here and must not be mixed: a PAIRING is
 * one stating rule and a CELL is one (ink, surface) square of the matrix. Three rules state one of today's two
 * ink-fill cells, so the two counts differ, and the unenforced figure is a difference of cells. */

import type { CheckOutcome } from "../lib/findings.ts";
import { EXCUSED_FROM_THE_TEXT_FLOOR, EXCUSED_ON_AN_INK_FILL, type Excuses } from "./excuses.ts";
import {
  INK_FILLED,
  TEXT_FLOOR,
  ratioOf,
  statedBelowItsFloor,
  textInks,
  textOnAnInkFill,
  type Ledger,
} from "./ledger.ts";
import { RULES, cellKey, type Audit } from "./rules.ts";

export interface CheckContrastInput {
  readonly ledger: Ledger;
  readonly ledgerFile: string;
  /**
   * The excuse lists to judge against. Both default to the declared records.
   *
   * Taken as input rather than read from `excuses.ts` so that the staleness rule and the skip an entry produces
   * are both reachable while the ink-fill list is empty. A guard reached by nothing is decoration.
   */
  readonly excusedOnPaper?: Excuses | undefined;
  readonly excusedOnAnInkFill?: Excuses | undefined;
}

function resolve(input: CheckContrastInput): Audit {
  const { ledger, ledgerFile } = input;
  const excusedOnPaper = input.excusedOnPaper ?? EXCUSED_FROM_THE_TEXT_FLOOR;
  const excusedOnAnInkFill = input.excusedOnAnInkFill ?? EXCUSED_ON_AN_INK_FILL;
  const textual = textInks(ledger);
  const statedOnAnInkFill = textOnAnInkFill(ledger);

  return {
    ledger,
    ledgerFile,
    excusedOnPaper,
    excusedOnAnInkFill,
    textual,
    enforcedOnPaper: textual.filter((ink) => !(ink in excusedOnPaper)),
    statedOnAnInkFill,
    enforcedCells: new Set(
      statedOnAnInkFill.flatMap((one) =>
        one.ink in excusedOnAnInkFill ? [] : [cellKey(one.ink, one.surface)],
      ),
    ),
  };
}

export async function checkContrast(input: CheckContrastInput): Promise<CheckOutcome> {
  const audit = resolve(input);
  const perRule = await Promise.all(RULES.map(async (rule) => rule.of(audit)));

  return { findings: perRule.flat(), notes: notesOn(audit) };
}

function notesOn(audit: Audit): string[] {
  const { ledger, textual, enforcedOnPaper, statedOnAnInkFill, enforcedCells } = audit;
  const cells = textual.length * INK_FILLED.length;
  const failing = ledger.pairs.filter((pair) => !pair.clears).length;

  return [
    `${String(ledger.pairs.length)} pair(s) computed from the token files, not claimed`,
    `${String(ledger.inks.length)} ink(s) and ${String(ledger.surfaces.length)} surface(s), read from ${String(ledger.sheets.length)} shipped stylesheet(s)`,
    `${String(enforcedOnPaper.length)} ink(s) held to ${String(TEXT_FLOOR)}:1 on both paper surfaces, derived from the ledger's own floors`,
    `${String(statedOnAnInkFill.length)} stated pairing(s) on ${INK_FILLED.join(" or ")}, covering ${String(enforcedCells.size)} of ${String(cells)} cell(s), each one a rule that names the fill and the ink together`,
    `${String(cells - enforcedCells.size)} of ${String(cells)} ink-on-ink-fill cell(s) recorded and not enforced, because no rule states them and no stylesheet can say which surface a class sits on`,
    `${String(Object.keys(audit.excusedOnPaper).length)} declared excuse(s) on paper, each asserted to describe an ink the product still writes as text`,
    `${String(Object.keys(audit.excusedOnAnInkFill).length)} declared excuse(s) on an ink-filled surface, each asserted to describe a pairing a rule states`,
    `${String(failing)} pair(s) do not clear the ink's floor and are recorded as pairings the product must not compose`,
    belowItsFloorNote(ledger),
    `${String(ledger.unmeasurable.length)} value(s) no ratio can describe, each recorded with the reason`,
  ];
}

/**
 * The stated pairings that do not clear their own floor, printed rather than enforced.
 *
 * A note does not fail the build, and this is deliberate: the gate holds stated pairings to the TEXT floor, so an
 * indicator's stated pairing below the INDICATOR floor is measured here and judged nowhere. Printing it puts the
 * figure in front of whoever has to decide whether the property was classified right, at no risk of reddening a
 * tree on an unresolved classification.
 */
function belowItsFloorNote(ledger: Ledger): string {
  const below = statedBelowItsFloor(ledger);
  if (below.length === 0) {
    return "0 stated pairing(s) fall below their own floor, over every floor and not only the text one";
  }
  const named = below
    .map(
      (one) =>
        `${one.ink} ${(ratioOf(ledger, one.ink, one.surface) ?? 0).toFixed(2)} against ` +
        `${String(one.floor)} on ${one.surface}, per ${one.where}`,
    )
    .join("; ");
  return `${String(below.length)} stated pairing(s) fall below their own floor and are measured rather than judged, because this gate holds a stated pairing to the text floor only: ${named}`;
}
