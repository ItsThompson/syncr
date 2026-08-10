/* THE AUDIT'S RULES, one function each, named in a list the gate composes.
 *
 * Each rule is a different question rather than a variation on one, and each returns its own findings instead of
 * pushing into a shared array. The list is exported because it is the structure a mutation sweep should enumerate:
 * a sweep that derives its targets from a regex over `if (` cannot see a whole rule going missing, and one that
 * reads this list can.
 *
 * COVERAGE. Every ink the shipped stylesheets draw with, and every surface they fill with, has a ratio against the
 * other. A pair without one is a pair nobody has measured. The matrix is complete by construction, so what this
 * actually checks is that the construction happened: that the palette was read, that every token in it resolved to
 * a colour, and that the committed document is the one this run produces.
 *
 * TEXT CLEARS ITS FLOOR ON EVERY PAPER SURFACE, over a set DERIVED FROM THE LEDGER rather than named here. An
 * earlier version enforced this for three inks it listed, on two surfaces, and a planted label ink measuring
 * 2.45:1 on `--paper` passed over 506 pairs: the rule is "every surface it can appear on", and a list of three is
 * not every ink. The set is every ink the ledger holds to the TEXT floor, which is every ink a `color` declaration
 * writes, so an ink the product starts writing is enforced the day it is written.
 *
 * TEXT CLEARS ITS FLOOR ON AN INK-FILLED SURFACE TOO, over the pairings the SHEETS STATE rather than over the
 * whole column. Paper needs no reachability argument, because every label can land on it. An ink fill does: the
 * matrix measures 22 inks against `--ink` and `--ink-deep` and nothing composes all but two of them, so enforcing
 * the column would report 22 pairs of which one is real and then be narrowed back to get green. What a stylesheet
 * CAN prove is a rule that declares its own fill and its own ink.
 *
 * WHAT THAT RULE CANNOT SEE, in two shapes, stated because a reader meets the rule before the limit.
 *
 * A rule filled `transparent` draws on whatever it is placed under, and no stylesheet says what that is. So a
 * control whose own fill is translucent, sitting inside an ink-filled container, is a pairing this gate is blind
 * to by construction. It is measured where a DOM exists, in `src/ui/domain/marks/__tests__/contrast.test.tsx`,
 * which renders the composition and computes the ratio from these same tokens. The class enforced here has never
 * failed; the class that has is that one. Both facts belong beside each other.
 *
 * A pairing split across two selectors that only meet in the DOM is invisible for the same reason: `.a` filling
 * and `.b` drawing compose only where the markup nests them. Two rules with the SAME selector in one file are a
 * different case and are read, because they compose by the cascade with nothing concatenated.
 *
 * AN INK EXCUSED FROM A FLOOR IS DECLARED, with the reason, in the shape the Python teardown guard's `EXEMPTED`
 * uses. The lists and the staleness rule they share are in `excuses.ts`.
 *
 * THE STRUCTURAL RULES the design language states in absolute terms are asserted too, because they are the pairs
 * the product composes on purpose: a control's border clears 3:1 on both paper surfaces, and `--rule-strong` is
 * banned on a control BECAUSE it measures 2.65:1 there. */

import { readFile } from "node:fs/promises";

import type { Finding } from "../lib/findings.ts";
import { deadExcuses, type Excuses } from "./excuses.ts";
import {
  INDICATOR_FLOOR,
  INK_FILLED,
  TEXT_FLOOR,
  ratioOf,
  type Composed,
  type Ledger,
} from "./ledger.ts";
import { renderLedger } from "./render.ts";

/* THE TWO PAPER SURFACES EVERY LABEL AND EVERY CONTROL BORDER CAN LAND ON. `--paper` is the page and
 * `--paper-raised` is a block, a panel and a control, and the design language's own rule is that a colour clears
 * its floor on every surface it can appear on rather than on the one its author had in mind. */
const PAPER = ["--paper", "--paper-raised"] as const;

/** The border a control draws, which is an indicator and must clear 3:1 wherever the control sits. */
const CONTROL_BORDER = "--rule-control";

/** Banned on a control: it measures 2.65:1 on raised paper, which is below the indicator floor. */
const NOT_ON_A_CONTROL = "--rule-strong";

/** Everything one run has read and derived, resolved once rather than re-derived by each rule. */
export interface Audit {
  readonly ledger: Ledger;
  readonly ledgerFile: string;
  readonly excusedOnPaper: Excuses;
  readonly excusedOnAnInkFill: Excuses;
  /** Every ink the ledger holds to the text floor. */
  readonly textual: readonly string[];
  /** The text inks enforced on paper, which is every one the paper excuses do not cover. */
  readonly enforcedOnPaper: readonly string[];
  /** The pairings a rule states on an ink fill: ONE ENTRY PER STATING RULE, which is not a count of cells. */
  readonly statedOnAnInkFill: readonly Composed[];
  /** The distinct matrix cells those rules cover. Three rules state one of today's two cells. */
  readonly enforcedCells: ReadonlySet<string>;
}

export type Rule = (audit: Audit) => Finding[] | Promise<Finding[]>;

function finding(file: string, check: string, message: string): Finding {
  return { file, check, message };
}

/** The key a matrix cell is counted under, so a rule count is never mistaken for a cell count. */
export function cellKey(ink: string, surface: string): string {
  return `${ink} ${surface}`;
}

/* Every rule below reads the matrix, and an ink whose pairs are missing would be enforced against nothing: the
 * enforcement sets are drawn from the pairs, so a row that vanished would take its own rule with it. */
const matrixIsComplete: Rule = ({ ledger, ledgerFile }) => {
  const expected = ledger.inks.length * ledger.surfaces.length;
  if (ledger.pairs.length === expected) return [];

  const missing = ledger.inks.filter(
    (ink) => ledger.pairs.filter((pair) => pair.ink === ink).length !== ledger.surfaces.length,
  );
  return [
    finding(
      ledgerFile,
      "incomplete-matrix",
      `${String(ledger.pairs.length)} pair(s) for ${String(ledger.inks.length)} ink(s) against ` +
        `${String(ledger.surfaces.length)} surface(s), which should be ${String(expected)}. ` +
        `A pair with no ratio is a pair nobody has measured. Short rows: ${missing.join(", ")}`,
    ),
  ];
};

/* A ledger that has drifted from the tokens is worse than none: it will be read, and it will be wrong. */
const theDocumentIsCurrent: Rule = async ({ ledger, ledgerFile }) => {
  const committed = await readFile(ledgerFile, "utf8").catch(() => null);
  if (committed === null) {
    return [
      finding(
        ledgerFile,
        "ledger-missing",
        "the committed ledger does not exist. Write it with --write.",
      ),
    ];
  }
  if (committed === renderLedger(ledger)) return [];
  return [
    finding(
      ledgerFile,
      "ledger-stale",
      "the committed ledger is not what these tokens produce. Regenerate it with --write and " +
        "read the diff: a ratio that moved is a retuned pigment, and a row that appeared is a " +
        "pair nobody had measured.",
    ),
  ];
};

const paperExcusesStillDescribeAnInk: Rule = ({ ledgerFile, excusedOnPaper, textual }) =>
  deadExcuses(excusedOnPaper, (ink) => textual.includes(ink)).map((dead) =>
    finding(
      ledgerFile,
      "a-dead-excuse",
      `${dead.ink} is excused from the text floor and no shipped declaration writes it as text any ` +
        `more, so the excuse describes nothing. It said: ${dead.reason}`,
    ),
  );

const inkFillExcusesStillDescribeAPairing: Rule = ({
  ledgerFile,
  excusedOnAnInkFill,
  statedOnAnInkFill,
}) =>
  deadExcuses(excusedOnAnInkFill, (ink) => statedOnAnInkFill.some((one) => one.ink === ink)).map(
    (dead) =>
      finding(
        ledgerFile,
        "a-dead-ink-fill-excuse",
        `${dead.ink} is excused from the text floor on an ink-filled surface and no rule states it ` +
          `there, so the excuse describes nothing. It said: ${dead.reason}`,
      ),
  );

const aControlBorderClearsTheIndicatorFloor: Rule = ({ ledger, ledgerFile }) =>
  PAPER.flatMap((surface) => {
    const border = ratioOf(ledger, CONTROL_BORDER, surface);
    if (border !== null && border >= INDICATOR_FLOOR) return [];
    return [
      finding(
        ledgerFile,
        "control-border-below-the-floor",
        `${CONTROL_BORDER} measures ${border === null ? "nothing" : border.toFixed(2)} against ` +
          `${surface}, and a control's border is an indicator: it has to clear ${String(INDICATOR_FLOOR)}:1 ` +
          "on every surface a control can sit on.",
      ),
    ];
  });

/* The ban is asserted as a MEASUREMENT rather than as a rule about a name: `--rule-strong` is banned on a control
 * because it is below the floor there, and if it were ever retuned above it the ban would be the thing to
 * revisit rather than something to keep quietly. */
const theBannedRuleIsStillBelowTheFloor: Rule = ({ ledger, ledgerFile }) =>
  PAPER.flatMap((surface) => {
    const banned = ratioOf(ledger, NOT_ON_A_CONTROL, surface);
    if (banned === null || banned < INDICATOR_FLOOR) return [];
    return [
      finding(
        ledgerFile,
        "the-banned-rule-now-clears",
        `${NOT_ON_A_CONTROL} measures ${banned.toFixed(2)} against ${surface}, which is at or above ` +
          "the indicator floor. It is banned on controls because it was below it; the ban and this " +
          "check both have to be revisited rather than one of them quietly kept.",
      ),
    ];
  });

const textClearsItsFloorOnPaper: Rule = ({ ledger, ledgerFile, enforcedOnPaper }) =>
  PAPER.flatMap((surface) =>
    enforcedOnPaper.flatMap((ink) => {
      const text = ratioOf(ledger, ink, surface);
      if (text !== null && text >= TEXT_FLOOR) return [];
      return [
        finding(
          ledgerFile,
          "text-below-the-floor",
          `${ink} measures ${text === null ? "nothing" : text.toFixed(2)} against ${surface}, and ` +
            `text has to clear ${String(TEXT_FLOOR)}:1 on every surface it can appear on. ` +
            `The declaration that made it text: ${floorFrom(ledger, ink)}.`,
        ),
      ];
    }),
  );

/* Enforcement and the excuse both key on the ink, so a rule that states an unreadable pairing names itself. */
const textClearsItsFloorOnAnInkFill: Rule = ({
  ledger,
  ledgerFile,
  excusedOnAnInkFill,
  statedOnAnInkFill,
}) =>
  statedOnAnInkFill.flatMap((one) => {
    if (one.ink in excusedOnAnInkFill) return [];
    const text = ratioOf(ledger, one.ink, one.surface);
    if (text !== null && text >= TEXT_FLOOR) return [];
    return [
      finding(
        ledgerFile,
        "text-below-the-floor-on-an-ink-fill",
        `${one.ink} measures ${text === null ? "nothing" : text.toFixed(2)} against ${one.surface}, ` +
          `and ${one.where} states that pairing outright: it fills with ${one.surface} and draws ` +
          `${one.ink} in the same rule, so text there has to clear ${String(TEXT_FLOOR)}:1.`,
      ),
    ];
  });

/* THE READING'S OWN CONTROL. The enforced set is derived, so a reader that stopped finding pairings would enforce
 * nothing and pass whatever the tree did. The product fills with ink in a panel header, a dialog header and a
 * selected day, so a run that reaches none of them has stopped working rather than found a clean tree. */
const theReadingReachedAnInkFill: Rule = ({ ledger, ledgerFile, statedOnAnInkFill }) => {
  if (statedOnAnInkFill.length > 0) return [];
  return [
    finding(
      ledgerFile,
      "no-ink-fill-composition-read",
      `no rule in ${String(ledger.sheets.length)} shipped stylesheet(s) states an ink drawn on ` +
        `${INK_FILLED.join(" or ")}, so the text floor was enforced on nothing there. The product ` +
        "fills with ink in a panel header, a dialog header and a selected day: a reading that finds " +
        "none of them has stopped working rather than found a clean tree.",
    ),
  ];
};

/** The declaration that put an ink at the text floor, so a finding names what to look at. */
function floorFrom(ledger: Ledger, ink: string): string {
  return ledger.pairs.find((pair) => pair.ink === ink)?.floorFrom ?? "nothing";
}

/**
 * Every rule the audit runs, in the order it reports them.
 *
 * Exported as a named list so a mutation sweep can enumerate the rules from the code's own structure. Removing an
 * entry here must redden something, which is the check a syntax-derived sweep cannot make.
 */
export const RULES: readonly { readonly name: string; readonly of: Rule }[] = [
  { name: "matrixIsComplete", of: matrixIsComplete },
  { name: "theDocumentIsCurrent", of: theDocumentIsCurrent },
  { name: "paperExcusesStillDescribeAnInk", of: paperExcusesStillDescribeAnInk },
  { name: "inkFillExcusesStillDescribeAPairing", of: inkFillExcusesStillDescribeAPairing },
  { name: "aControlBorderClearsTheIndicatorFloor", of: aControlBorderClearsTheIndicatorFloor },
  { name: "theBannedRuleIsStillBelowTheFloor", of: theBannedRuleIsStillBelowTheFloor },
  { name: "textClearsItsFloorOnPaper", of: textClearsItsFloorOnPaper },
  { name: "textClearsItsFloorOnAnInkFill", of: textClearsItsFloorOnAnInkFill },
  { name: "theReadingReachedAnInkFill", of: theReadingReachedAnInkFill },
];
