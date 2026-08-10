/* THE AUDIT'S VERDICT ON THE PALETTE, over the ledger the tokens produce.
 *
 * The rules below are different questions rather than variations on one.
 *
 * COVERAGE. Every ink the shipped stylesheets draw with, and every surface they fill with, has a ratio against the
 * other. A pair without one is a pair nobody has measured, which is what section 19 refuses. The matrix is
 * complete by construction, so what this actually checks is that the construction happened: that the palette was
 * read, that every token in it resolved to a colour, and that the committed document is the one this run produces.
 *
 * TEXT CLEARS ITS FLOOR ON EVERY PAPER SURFACE, over a set DERIVED FROM THE LEDGER rather than named here. The
 * first version enforced this for three inks it listed, on two surfaces, and a planted label ink measuring 2.45:1
 * on `--paper` shipped green over 506 pairs: the criterion says "every surface it can appear on", and a list of
 * three is not every ink. The set is now every ink the ledger holds to the TEXT floor, which is every ink a
 * `color` declaration writes, so an ink the product starts writing is enforced the day it is written.
 *
 * TEXT CLEARS ITS FLOOR ON AN INK-FILLED SURFACE TOO, over the pairings the SHEETS STATE rather than over the
 * whole column. Paper needs no reachability argument, because every label can land on it. An ink fill does: the
 * matrix measures 22 inks against `--ink` and `--ink-deep` and nothing composes 21 of them, so enforcing the
 * column would report 22 pairs of which one is real and then be narrowed back to get green. What a stylesheet CAN
 * prove is a rule that declares its own fill and its own ink, and that set is enforced here.
 *
 * WHAT THIS RULE CANNOT SEE, stated because a reader meets the rule before the limit. A rule filled `transparent`
 * draws on whatever it is placed under, and no stylesheet says what that is. So a control whose own fill is
 * translucent, sitting inside an ink-filled container, is a pairing this gate is blind to by construction: it is
 * measured where a DOM exists, in `src/ui/domain/marks/__tests__/contrast.test.tsx`, which renders the
 * composition and computes the ratio from these same tokens. The class enforced here has never failed; the class
 * that has is the one above. Both facts belong beside each other.
 *
 * AN INK EXCUSED FROM THAT RULE IS DECLARED, with the reason, in the shape the Python teardown guard's `EXEMPTED`
 * uses: enumerated rather than recognised, and asserted to match something real, so an excuse cannot outlive the
 * case it was written for. There is one list per surface class, because an ink excused on paper is not thereby
 * excused on an ink fill and the reverse: `--on-ink` is excused on paper for measuring 1.08:1 there, and it is
 * the ink of every pairing the sheets state on an ink fill. Every ink excused today has a structural guard
 * elsewhere that is stronger than a ratio.
 *
 * THE STRUCTURAL RULES section 19 states in absolute terms are asserted too, because they are the pairs the
 * product composes on purpose: a control's border clears 3:1 on both paper surfaces, and `--rule-strong` is banned
 * on a control BECAUSE it measures 2.65:1 there. */

import { readFile } from "node:fs/promises";

import type { CheckOutcome, Finding } from "../lib/findings.ts";
import {
  INDICATOR_FLOOR,
  INK_FILLED,
  TEXT_FLOOR,
  ratioOf,
  textInks,
  textOnAnInkFill,
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

/**
 * The inks excused from the text floor on a paper surface, each with the reason and the guard that replaces it.
 *
 * Declared rather than recognised. All three are inks a `color` declaration writes, so the derivation finds them,
 * and each is excused for a reason a ratio cannot express: one is not on paper at all, one is not text, and one is
 * a track rather than a reading.
 *
 * Exported so the gate's own cases can carry them: a synthetic ledger that omitted them would leave every excuse
 * describing nothing, which this check refuses in that direction too.
 */
export const EXCUSED_FROM_THE_TEXT_FLOOR: Readonly<Record<string, string>> = {
  "--on-ink":
    "it exists for an ink-filled surface and measures 14.83:1 there. On paper it is 1.08:1 and could " +
    "not be otherwise; what keeps it off paper is that the only rules writing it are an ink header's own",
  "--signal-amber":
    "amber has no text step: it is written on a MARK, which is an indicator at 3:1, and it measures " +
    "4.52:1 on raised paper against 4.18:1 on the page. What forbids it on prose is structural rather " +
    "than numeric, in src/ui/domain/__tests__/pigment.test.ts, which refuses a signal pigment on any " +
    "selector that is not always a glyph",
  "--rule":
    "the one declaration writing it as text is the bounded meter's UNFILLED run, which is a track " +
    "rather than a reading: every cell is aria-hidden, the value is on the meter's own role, and the " +
    "row states the samples and the percentage beside it. charts.css carries that disclosure at the " +
    "rule itself, with the 1.71:1 figure",
};

/** Every ink the enforcement excuses, for a case that needs the set rather than the reasons. */
export const EXCUSED_TEXT_INKS: readonly string[] = Object.keys(EXCUSED_FROM_THE_TEXT_FLOOR);

/**
 * The excuses that describe nothing, which is the staleness rule run in the other direction.
 *
 * An excuse is only checkable while the case it was written for still exists. Both excuse sets are held to it,
 * with a different notion of "still exists": an ink the product no longer writes as text, and a pairing no rule
 * states any more.
 */
export function deadExcuses(
  excused: Readonly<Record<string, string>>,
  describesSomething: (ink: string) => boolean,
): { readonly ink: string; readonly reason: string }[] {
  return Object.entries(excused).flatMap(([ink, reason]) =>
    describesSomething(ink) ? [] : [{ ink, reason }],
  );
}

/**
 * The inks excused from the text floor on an ink-filled surface, each with the reason and the guard that replaces
 * it, in the same shape the paper excuses take.
 *
 * EMPTY, AND THAT IS A MEASUREMENT RATHER THAN AN OMISSION. Every pairing the sheets state on an ink fill is
 * `--on-ink`, at 11.50:1 on `--ink` and 14.83:1 on `--ink-deep`, so nothing needs excusing. It is declared
 * because the day a rule states an ink fill under an ink that cannot clear there, the choice is to fix the rule
 * or to say here why a ratio is the wrong instrument for it -- and an excuse added to get green is held to
 * describing a pairing some rule really states, by the same both-ways rule the paper excuses carry.
 *
 * SEPARATE FROM THE PAPER SET ON PURPOSE. `--on-ink` is excused on paper and is the ink of every ink-fill
 * composition there is; one shared list would excuse it here too and leave this rule enforcing nothing.
 */
export const EXCUSED_ON_AN_INK_FILL: Readonly<Record<string, string>> = {};

function finding(file: string, check: string, message: string): Finding {
  return { file, check, message };
}

export interface CheckContrastInput {
  readonly ledger: Ledger;
  readonly ledgerFile: string;
}

export async function checkContrast(input: CheckContrastInput): Promise<CheckOutcome> {
  const { ledger, ledgerFile } = input;
  const findings: Finding[] = [];
  const enforced = textInks(ledger).filter((ink) => !(ink in EXCUSED_FROM_THE_TEXT_FLOOR));

  /* THE MATRIX HAS TO BE COMPLETE, because every rule below reads it and an ink whose pairs are missing would be
   * enforced against nothing: the derived enforcement set is drawn from the pairs, so a row that vanished would
   * take its own rule with it. The builder produces a pair per ink per surface by construction, which makes this
   * a check on the construction rather than on the palette -- and it is the one that makes "a pair without a ratio
   * fails the audit" true of the gate rather than only of the document. */
  const expected = ledger.inks.length * ledger.surfaces.length;
  if (ledger.pairs.length !== expected) {
    const missing = ledger.inks.filter(
      (ink) => ledger.pairs.filter((pair) => pair.ink === ink).length !== ledger.surfaces.length,
    );
    findings.push(
      finding(
        ledgerFile,
        "incomplete-matrix",
        `${String(ledger.pairs.length)} pair(s) for ${String(ledger.inks.length)} ink(s) against ` +
          `${String(ledger.surfaces.length)} surface(s), which should be ${String(expected)}. ` +
          `A pair with no ratio is a pair nobody has measured. Short rows: ${missing.join(", ")}`,
      ),
    );
  }

  /* The document, regenerated and compared. A ledger that has drifted from the tokens is worse than none: it will
   * be read, and it will be wrong. */
  const rendered = renderLedger(ledger);
  const committed = await readFile(ledgerFile, "utf8").catch(() => null);
  if (committed === null) {
    findings.push(
      finding(
        ledgerFile,
        "ledger-missing",
        "the committed ledger does not exist. Write it with --write.",
      ),
    );
  } else if (committed !== rendered) {
    findings.push(
      finding(
        ledgerFile,
        "ledger-stale",
        "the committed ledger is not what these tokens produce. Regenerate it with --write and " +
          "read the diff: a ratio that moved is a retuned pigment, and a row that appeared is a " +
          "pair nobody had measured.",
      ),
    );
  }

  /* An excuse for an ink the product no longer writes as text is an excuse nobody can check, so it fails in that
   * direction too: the same both-ways staleness rule the teardown guard's declared exemptions carry. */
  const written = textInks(ledger);
  for (const dead of deadExcuses(EXCUSED_FROM_THE_TEXT_FLOOR, (ink) => written.includes(ink))) {
    findings.push(
      finding(
        ledgerFile,
        "a-dead-excuse",
        `${dead.ink} is excused from the text floor and no shipped declaration writes it as text any ` +
          `more, so the excuse describes nothing. It said: ${dead.reason}`,
      ),
    );
  }

  /* The same rule for the ink-fill excuses, and it is what keeps that list honest when it is empty: an entry
   * there has to describe a pairing some rule states, or it is silencing a red that describes nothing. */
  const composedOnInkFills = textOnAnInkFill(ledger);
  for (const dead of deadExcuses(EXCUSED_ON_AN_INK_FILL, (ink) =>
    composedOnInkFills.some((one) => one.ink === ink),
  )) {
    findings.push(
      finding(
        ledgerFile,
        "a-dead-ink-fill-excuse",
        `${dead.ink} is excused from the text floor on an ink-filled surface and no rule states it ` +
          `there, so the excuse describes nothing. It said: ${dead.reason}`,
      ),
    );
  }

  for (const surface of PAPER) {
    const border = ratioOf(ledger, CONTROL_BORDER, surface);
    if (border === null || border < INDICATOR_FLOOR) {
      findings.push(
        finding(
          ledgerFile,
          "control-border-below-the-floor",
          `${CONTROL_BORDER} measures ${border === null ? "nothing" : border.toFixed(2)} against ` +
            `${surface}, and a control's border is an indicator: it has to clear ${String(INDICATOR_FLOOR)}:1 ` +
            "on every surface a control can sit on.",
        ),
      );
    }

    /* The ban is asserted as a MEASUREMENT rather than as a rule about a name: it is banned on a control because it
     * is below the floor there, and if it were ever retuned above it the ban would be the thing to revisit. */
    const banned = ratioOf(ledger, NOT_ON_A_CONTROL, surface);
    if (banned !== null && banned >= INDICATOR_FLOOR) {
      findings.push(
        finding(
          ledgerFile,
          "the-banned-rule-now-clears",
          `${NOT_ON_A_CONTROL} measures ${banned.toFixed(2)} against ${surface}, which is at or above ` +
            "the indicator floor. It is banned on controls because it was below it; the ban and this " +
            "check both have to be revisited rather than one of them quietly kept.",
        ),
      );
    }

    for (const ink of enforced) {
      const text = ratioOf(ledger, ink, surface);
      if (text === null || text < TEXT_FLOOR) {
        findings.push(
          finding(
            ledgerFile,
            "text-below-the-floor",
            `${ink} measures ${text === null ? "nothing" : text.toFixed(2)} against ${surface}, and ` +
              `text has to clear ${String(TEXT_FLOOR)}:1 on every surface it can appear on. ` +
              `The declaration that made it text: ${floorFrom(ledger, ink)}.`,
          ),
        );
      }
    }
  }

  /* THE INK FILLS, over the stated pairings rather than over the column. Enforcement and the excuse both key on
   * the ink, so a rule that states an unreadable pairing names itself in the finding. */
  for (const one of composedOnInkFills) {
    if (one.ink in EXCUSED_ON_AN_INK_FILL) continue;
    const text = ratioOf(ledger, one.ink, one.surface);
    if (text === null || text < TEXT_FLOOR) {
      findings.push(
        finding(
          ledgerFile,
          "text-below-the-floor-on-an-ink-fill",
          `${one.ink} measures ${text === null ? "nothing" : text.toFixed(2)} against ${one.surface}, ` +
            `and ${one.where} states that pairing outright: it fills with ${one.surface} and draws ` +
            `${one.ink} in the same rule, so text there has to clear ${String(TEXT_FLOOR)}:1.`,
        ),
      );
    }
  }

  /* THE READING'S OWN CONTROL. The set above is derived, so a reader that stopped finding compositions would
   * enforce nothing and pass whatever the tree did -- the same vacuous green a list-of-three once shipped. The
   * product fills with ink in a panel header, a dialog header and a selected day, so a run that reaches none of
   * them has stopped working rather than found nothing. */
  if (composedOnInkFills.length === 0) {
    findings.push(
      finding(
        ledgerFile,
        "no-ink-fill-composition-read",
        `no rule in ${String(ledger.sheets.length)} shipped stylesheet(s) states an ink drawn on ` +
          `${INK_FILLED.join(" or ")}, so the text floor was enforced on nothing there. The product ` +
          "fills with ink in a panel header, a dialog header and a selected day: a reading that finds " +
          "none of them has stopped working rather than found a clean tree.",
      ),
    );
  }

  const failing = ledger.pairs.filter((pair) => !pair.clears);
  const inkFillPairs = textInks(ledger).length * INK_FILLED.length;

  return {
    findings,
    notes: [
      `${ledger.pairs.length} pair(s) computed from the token files, not claimed`,
      `${ledger.inks.length} ink(s) and ${ledger.surfaces.length} surface(s), read from ${String(ledger.sheets.length)} shipped stylesheet(s)`,
      `${enforced.length} ink(s) held to ${String(TEXT_FLOOR)}:1 on both paper surfaces, derived from the ledger's own floors`,
      `${composedOnInkFills.length} stated pairing(s) held to ${String(TEXT_FLOOR)}:1 on ${INK_FILLED.join(" or ")}, each one a rule that names the fill and the ink together`,
      `${String(inkFillPairs - composedOnInkFills.length)} of ${String(inkFillPairs)} ink-on-ink-fill pairing(s) recorded and not enforced, because no rule states them and no stylesheet can say which surface a class sits on`,
      `${Object.keys(EXCUSED_FROM_THE_TEXT_FLOOR).length} declared excuse(s), each asserted to describe an ink the product still writes as text`,
      `${Object.keys(EXCUSED_ON_AN_INK_FILL).length} declared excuse(s) on an ink-filled surface, each asserted to describe a pairing a rule states`,
      `${failing.length} pair(s) do not clear the ink's floor and are recorded as pairings the product must not compose`,
      `${ledger.unmeasurable.length} value(s) no ratio can describe, each recorded with the reason`,
    ],
  };
}

/** The declaration that put an ink at the text floor, so a finding names what to look at. */
function floorFrom(ledger: Ledger, ink: string): string {
  return ledger.pairs.find((pair) => pair.ink === ink)?.floorFrom ?? "nothing";
}
