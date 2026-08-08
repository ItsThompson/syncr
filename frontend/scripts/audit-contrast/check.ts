/* THE AUDIT'S VERDICT ON THE PALETTE, over the ledger the tokens produce.
 *
 * Two rules, and they are different questions.
 *
 * COVERAGE. Every ink the shipped stylesheets draw with, and every surface they fill with, has a ratio against the
 * other. A pair without one is a pair nobody has measured, which is what section 19 refuses: "a new colour pair
 * without a computed ratio against every reachable surface fails review". The matrix is complete by construction,
 * so what this actually checks is that the construction happened -- that the palette was read, that every token in
 * it resolved to a colour, and that the committed document is the one this run produces.
 *
 * THE STRUCTURAL RULES the design language states in absolute terms, which are the ones a stylesheet can break
 * without anybody noticing: a control's border must clear 3:1 on both paper surfaces, `--rule-strong` is banned on
 * a control because it measures 2.65:1 there, and text must clear 4.5:1 on every paper surface. Those are
 * asserted, not merely recorded, because they are the pairs the product composes on purpose. */

import { readFile } from "node:fs/promises";

import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { INDICATOR_FLOOR, TEXT_FLOOR, type Ledger } from "./ledger.ts";
import { renderLedger } from "./render.ts";

export interface CheckContrastInput {
  readonly ledger: Ledger;
  readonly ledgerFile: string;
}

/* THE TWO PAPER SURFACES EVERY LABEL AND EVERY CONTROL BORDER CAN LAND ON. `--paper` is the page and
 * `--paper-raised` is a block, a panel and a control, and the design language's own rule is that a colour clears
 * its floor on every surface it can appear on rather than on the one its author had in mind. */
const PAPER = ["--paper", "--paper-raised"] as const;

/** The border a control draws, which is an indicator and must clear 3:1 wherever the control sits. */
const CONTROL_BORDER = "--rule-control";

/** Banned on a control: it measures 2.65:1 on raised paper, which is below the indicator floor. */
const NOT_ON_A_CONTROL = "--rule-strong";

/** The ink a label takes on either paper surface. */
const LABEL_INKS = ["--ink", "--ink-deep", "--text-muted"] as const;

function ratioOf(ledger: Ledger, ink: string, surface: string): number | null {
  return ledger.pairs.find((pair) => pair.ink === ink && pair.surface === surface)?.ratio ?? null;
}

function finding(file: string, check: string, message: string): Finding {
  return { file, check, message };
}

export async function checkContrast(input: CheckContrastInput): Promise<CheckOutcome> {
  const { ledger, ledgerFile } = input;
  const findings: Finding[] = [];

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

    for (const ink of LABEL_INKS) {
      const text = ratioOf(ledger, ink, surface);
      if (text === null || text < TEXT_FLOOR) {
        findings.push(
          finding(
            ledgerFile,
            "text-below-the-floor",
            `${ink} measures ${text === null ? "nothing" : text.toFixed(2)} against ${surface}, and ` +
              `text has to clear ${String(TEXT_FLOOR)}:1 on every surface it can appear on.`,
          ),
        );
      }
    }
  }

  const failing = ledger.pairs.filter((pair) => !pair.clears);

  return {
    findings,
    notes: [
      `${ledger.pairs.length} pair(s) computed from the token files, not claimed`,
      `${ledger.inks.length} ink(s) and ${ledger.surfaces.length} surface(s), read from ${String(ledger.sheets.length)} shipped stylesheet(s)`,
      `${failing.length} pair(s) do not clear the ink's floor and are recorded as pairings the product must not compose`,
      `${ledger.unmeasurable.length} value(s) no ratio can describe, each recorded with the reason`,
    ],
  };
}
