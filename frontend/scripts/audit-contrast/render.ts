/* THE LEDGER AS A COMMITTED DOCUMENT, AND THE CHECK THAT IT IS THE ONE THE TOKENS PRODUCE.
 *
 * A generated file in the tree is only worth having if something fails when it drifts. So the document carries no
 * figure a reader has to trust: the script writes it, and `--check` regenerates it and refuses a difference, which
 * is the same mechanism the OpenAPI document and the generated client are held by.
 *
 * WHY A DOCUMENT AT ALL, when the ratios are computed in a test. Because the ledger is what a review READS. The
 * question "does this new pigment clear its floor on every surface it can reach" is answered by looking at a row,
 * and a row that does not exist is the answer to "has anyone measured this pair". A test can refuse a bad pair; a
 * ledger is how a reader finds the good ones. */

import { relative } from "node:path";

import type { Composed, Ledger, Pair } from "./ledger.ts";
import {
  INDICATOR_FLOOR,
  INK_FILLED,
  TEXT_FLOOR,
  ratioOf,
  textInks,
  textOnAnInkFill,
} from "./ledger.ts";
import { repoRoot } from "../lib/paths.ts";

const HEADER = `# Contrast ledger

**Generated. Do not edit.** Produced by \`npm run lint:contrast -- --write\` in \`frontend/\`, and
regenerated in CI by \`npm run lint:contrast\`, which fails on any difference.

Every ink the shipped stylesheets draw with, against every surface they fill with, with the ratio
computed from \`frontend/src/tokens/\` on the way past. Nothing here is claimed.

A cell that does not clear its floor is not automatically a defect: \`--on-ink\` on \`--paper\` is
1.08:1 and could not be otherwise, because that ink exists for an ink-filled surface. What a cell
with no ratio would be is a pair nobody has measured, and the audit refuses one.

| Floor | Applies to |
|---|---|
| ${TEXT_FLOOR.toFixed(1)}:1 | text, at every size this product sets |
| ${INDICATOR_FLOOR.toFixed(1)}:1 | an indicator: a border, a rule, a dot, a glyph |

The floor shown per row is the strictest one any shipped declaration puts that ink to, classified by
the property that writes it: a label's floor is 4.5:1 and a border's is 3:1, and a \`color\` on a rule
that also paints a hatch is a carrier for the hatch's own \`currentColor\` rather than text. A GLYPH is
a mark and its own floor is 3:1, which no property can tell from a label: an ink used only on a mark
is therefore shown against the stricter floor here, and the structural rule that no prose may take a
signal pigment is asserted in \`frontend/src/ui/domain/__tests__/pigment.test.ts\` instead.
`;

function cell(pair: Pair): string {
  return `${pair.ratio.toFixed(2)}${pair.clears ? "" : " ✗"}`;
}

/* THE INK FILLS, PUBLISHED AS MEASUREMENTS AND NOTHING ELSE.
 *
 * These rows carry no verdict mark, and that is the point of the section: which surface a class sits on is a fact
 * about the DOM, no stylesheet states it, and most of these pairings are composed by nothing. A ✗ here would read
 * as a defect list when it is a reference. The pairings the sheets DO state are the second table, and those are
 * the ones the audit holds to the text floor.
 *
 * Every count is derived from the tables above it, because this file's own totals are the figures a reader would
 * otherwise have to trust. */
function inkFilledSection(ledger: Ledger): string[] {
  const text = textInks(ledger);
  const head = ["ink", ...INK_FILLED.map((surface) => `\`${surface}\``)];
  const stated = textOnAnInkFill(ledger);

  return [
    "## What lands on an ink-filled surface",
    "",
    `\`${INK_FILLED.join("` and `")}\` are the fills that are ink rather than paper, and an ink chosen to be`,
    "read on paper is not readable on either. Every ink the product writes as text is measured against both",
    "here, so the pairing is on record whether or not anything composes it.",
    "",
    "| " + head.join(" | ") + " |",
    `|${head.map(() => "---").join("|")}|`,
    ...text.map(
      (ink) =>
        `| \`${ink}\` | ` +
        INK_FILLED.map((surface) => (ratioOf(ledger, ink, surface) ?? 0).toFixed(2)).join(" | ") +
        " |",
    ),
    "",
    `${text.length} ink(s) written as text, against ${INK_FILLED.length} ink-filled surface(s): ` +
      `${text.length * INK_FILLED.length} pairing(s) measured.`,
    "",
    "### The pairings a rule states",
    "",
    "A rule that declares its own fill and its own ink names both halves of a pairing in one place, which no",
    "DOM is needed to read. Those are the pairings held to the text floor on an ink fill; the rest of the",
    "table above is recorded and not enforced, because nothing says a class reaches that surface.",
    "",
    "| rule | ink | fill | ratio |",
    "|---|---|---|---|",
    ...stated.map((one: Composed) => {
      const ratio = ratioOf(ledger, one.ink, one.surface) ?? 0;
      return `| \`${one.where}\` | \`${one.ink}\` | \`${one.surface}\` | ${ratio.toFixed(2)} |`;
    }),
    "",
    `${stated.length} pairing(s) stated on an ink-filled surface, of ${ledger.composed.length} ` +
      `stated on any surface, held to ${TEXT_FLOOR.toFixed(1)}:1.`,
    "",
  ];
}

/** The ledger as the committed markdown, one row per ink and one column per surface. */
export function renderLedger(ledger: Ledger): string {
  const head = ["ink", "floor", ...ledger.surfaces.map((one) => `\`${one}\``)];
  const rows = ledger.inks.map((ink) => {
    const forInk = ledger.pairs.filter((pair) => pair.ink === ink);
    const floor = forInk[0]?.floor ?? INDICATOR_FLOOR;
    return [
      `\`${ink}\``,
      `${floor.toFixed(1)}:1`,
      ...ledger.surfaces.map((surface) => {
        const pair = forInk.find((one) => one.surface === surface);
        return pair === undefined ? "" : cell(pair);
      }),
    ];
  });

  const failing = ledger.pairs.filter((pair) => !pair.clears).length;

  return [
    HEADER,
    `## The matrix`,
    "",
    `| ${head.join(" | ")} |`,
    `|${head.map(() => "---").join("|")}|`,
    ...rows.map((row) => `| ${row.join(" | ")} |`),
    "",
    `${ledger.pairs.length} pair(s) measured, ${ledger.inks.length} ink(s) against ${ledger.surfaces.length} surface(s). ${failing} do not clear the ink's floor and are marked ✗, which means the pairing must not be composed rather than that a token is wrong.`,
    "",
    ...inkFilledSection(ledger),
    "## Which declaration set each floor",
    "",
    "An ink used both as a label and as a border is held to the label's floor, so the row's floor is the",
    "strictest shipped use. This names that use, because the classification is checkable rather than",
    "something to take on trust: a `color` on a rule that also paints a hatch is a carrier for the",
    "hatch's own `currentColor` rather than text, and is held to the indicator floor for that reason.",
    "",
    "| ink | floor | set by |",
    "|---|---|---|",
    ...ledger.inks.map((ink) => {
      const pair = ledger.pairs.find((one) => one.ink === ink);
      return `| \`${ink}\` | ${(pair?.floor ?? INDICATOR_FLOOR).toFixed(1)}:1 | \`${pair?.floorFrom ?? "nothing"}\` |`;
    }),
    "",
    "## What no ratio can describe",
    "",
    "Four shapes are not a flat colour and are recorded rather than measured, because a ratio computed",
    "for one of them would be a made-up figure. A hatch's own ink is measured where its mix percentage",
    "is known, in `frontend/src/ui/domain/charts/__tests__/contrast.test.ts`.",
    "",
    "| where | value | why |",
    "|---|---|---|",
    ...ledger.unmeasurable.map((one) => `| \`${one.token}\` | \`${one.value}\` | ${one.reason} |`),
    "",
    "## What the palette was read from",
    "",
    ...ledger.sheets.map((sheet) => `- \`frontend/src/${sheet}\``),
    "",
  ].join("\n");
}

/** Where the committed ledger lives, relative to the repository root, for a finding to name. */
export function ledgerPathIn(absolute: string): string {
  return relative(repoRoot, absolute);
}
