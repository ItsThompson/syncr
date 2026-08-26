/* THE VERDICT PANEL ON THE PROBE PAGE, AND THE CLIPPED EDGE THE GATE NOW MEASURES.
 *
 * WHY THIS IS IN A BROWSER RATHER THAN IN A TEST. The panel's whole correctness is one height: `--verdict-h` is
 * reserved (`verdict.css`), the rows scroll inside it, and the clipped edge of the fourth tradeoff row is the scroll
 * affordance -- the visible proof that more rows exist with no scrollbar drawn. Whether that edge is actually visible
 * at 226px is a RENDERED-PIXEL claim: jsdom lays nothing out, so every stylesheet reading can only assert that the
 * declarations exist, not that the browser composes them into a partially visible row. This page composes it.
 *
 * WHAT IS ASSERTED, AND WHY BOTH HALVES ARE NEEDED. The fourth row's top edge has to sit INSIDE the panel, and its
 * bottom edge has to lie BEYOND the panel's clip. Either half alone admits the failure it is paired against: a height
 * shortened until three rows fill the panel pushes the fourth row's top past the clip, and a height grown to hold all
 * four rows leaves the fourth row's bottom inside it. The relation is read off the boxes a browser reports, so no
 * figure from the stylesheet is restated here and no arithmetic can drift from the token.
 *
 * THE MARKUP IS THE ONE `VerdictPanel.tsx` WRITES for an infeasible probe verdict enumerating four offers and no
 * concessions, with no controls. `src/ui/domain/verdict-panel/__tests__/probe.test.tsx` renders the real component
 * over the same inputs and requires this markup to match its subtree exactly, so a drifted copy measures a panel the
 * product does not ship. The headline and provenance wordings come from the domain's own module rather than being
 * restated, because they are import-free and therefore reachable from a script. */

import path from "node:path";

import {
  provenanceReading,
  verdictHeadline,
  type PanelVerdict,
  type VerdictTradeoff,
} from "../../src/ui/domain/verdict-panel/verdict.ts";
import { frontendRoot } from "../lib/paths.ts";
import type { Finding } from "../lib/findings.ts";

/** Where the page reports what it measured about the panel and its rows. */
export const VERDICT_READINGS_ID = "verdict-readings";

/** How far a measured edge may sit from the clip before the two count as touching. Sub-pixel rounding, nothing more:
 * a sliver thinner than this is indistinguishable from no affordance at rendering's rounding. */
export const CLIP_TOLERANCE_PX = 0.5;

/** The case is defined by four tradeoff rows: three the panel holds whole, and the fourth whose clipped edge
 * shows. */
export const ROW_COUNT = 4;

/** The width the design record measures the panel at (`docs/design/components.html`). The product's own width is
 * fluid; pinning the record's width here keeps the measured rendering the one the record describes. */
export const PANEL_WIDTH_PX = 404;

/** The sheet that owns the height rule, which is where a failed finding points. Absolute, which is what the
 * reporter relativises against the repository root. */
const SHEET = path.join(frontendRoot, "src", "ui", "domain", "verdict-panel", "verdict.css");

/** The four offers the case enumerates, in the api's own per-kind wording. */
const OFFERS: readonly VerdictTradeoff[] = [
  {
    kind: "accept_partial",
    label: "Accept partial delivery on F&F Past Papers",
    targetId: "t1",
    recovers: "up to 1h20m",
  },
  {
    kind: "drop_item",
    label: "Drop Read for this week",
    targetId: "t2",
    recovers: "up to 45m",
  },
  {
    kind: "reduce_routine",
    label: "Reduce Sleep by 30m on Mon, Tue and Wed",
    targetId: "t3",
    recovers: "up to 1h30m",
  },
  {
    kind: "breach_floor",
    label: "Breach the Fitness floor by 20m",
    targetId: "t4",
    recovers: "up to 20m",
  },
];

/** The verdict the case renders: four enumerated offers and no concession, which is a panel holding exactly the
 * four rows the clipped-edge question is asked of. Exported because the probe-parity test renders the real panel
 * over exactly this input. */
export const CASE_VERDICT: PanelVerdict = {
  provenance: "probe",
  isFeasible: false,
  capacityIsSufficient: false,
  shortfalls: [],
  tradeoffs: OFFERS,
};

function verdictSectionRow(offer: VerdictTradeoff): string {
  /* THE SAME SHAPE `TradeoffRow` WRITES: the recovery span exists only where the reading sized one, rather than
   * rendering an empty promise beside an unsized offer. */
  const gap =
    offer.recovers === null
      ? ""
      : `<span class="verdict-panel__gap">recovers ${offer.recovers}</span>`;
  return (
    `<div class="verdict-panel__row">` +
    `<p class="verdict-panel__statement">${offer.label}${gap}</p>` +
    `</div>`
  );
}

/* THE SHORTFALL ROW IS `ShortfallRow`'s and carries reason rows of its own; the case deliberately renders none.
 * The affordance the gate measures is where the scroll ENDS, and a shortfall row ahead of the offers would move
 * the clipped edge onto an offer the reader cannot see at all. Four offer rows and nothing else is the shape the
 * question is asked of. */

/** What one row reported about where it sits relative to the page. */
export interface VerdictRowReading {
  readonly topPx: number;
  readonly bottomPx: number;
}

/** What the page reports about the rendered panel, or the reason it could measure nothing. */
export interface VerdictReport {
  /** Present only where the page could measure nothing at all, which is a fault in the instrument. */
  readonly error?: string | undefined;
  readonly panelBottomPx?: number | undefined;
  readonly rows?: readonly VerdictRowReading[] | undefined;
}

/** The container pins the record's width; the panel inside is styled entirely by the built bundle. */
export const VERDICT_SECTION = {
  style: `#verdict { width: ${String(PANEL_WIDTH_PX)}px }`,
  html:
    `<div id="verdict">` +
    `<section class="verdict-panel" aria-label="Verdict">` +
    `<div class="verdict-panel__head">` +
    `<p class="verdict-panel__headline">${verdictHeadline(CASE_VERDICT, 0)}</p>` +
    `<p class="verdict-panel__provenance">${provenanceReading("probe")}</p>` +
    `</div>` +
    `<div class="verdict-panel__rows">${OFFERS.map(verdictSectionRow).join("")}</div>` +
    `</section></div>`,
  script: `
  (() => {
    const report = (value) => {
      document.getElementById(${JSON.stringify(VERDICT_READINGS_ID)}).textContent = JSON.stringify(value);
    };
    const panel = document.querySelector(".verdict-panel");
    if (panel === null) {
      report({ error: "the page rendered no verdict panel" });
      return;
    }
    report({
      panelBottomPx: panel.getBoundingClientRect().bottom,
      rows: [...panel.querySelectorAll(".verdict-panel__row")].map((row) => {
        const box = row.getBoundingClientRect();
        return { topPx: box.top, bottomPx: box.bottom };
      }),
    });
  })();
`,
} as const;

export function parseVerdictReport(text: string): VerdictReport | null {
  if (text.trim() === "") return null;
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as VerdictReport)
      : null;
  } catch {
    return null;
  }
}

/* WHAT THE CLIP DOES. The bottom-most row straddles the panel's bottom edge: its top inside, its bottom beyond.
 * A finding names whichever half is missing, because the two failures have two different causes -- a token shrunk
 * until the held rows fill the panel, or one grown until nothing is left to reveal. The LAST row is the one whose
 * clipped edge shows, whatever kind wrote it: the affordance is a property of where the scroll ends, not of the
 * row that happens to sit there. */
export function verdictFindings(report: VerdictReport | null): Finding[] {
  if (
    report === null ||
    report.error !== undefined ||
    report.panelBottomPx === undefined ||
    report.rows === undefined
  ) {
    return [
      {
        file: SHEET,
        check: "rendered-verdict",
        message:
          "the page reported no geometry for the verdict panel, so nothing about its rendered height was measured. " +
          "The panel is drawn only once the page's own script runs, so a missing reading is a fault in the " +
          "instrument rather than a pass.",
      },
    ];
  }
  if (report.rows.length !== ROW_COUNT) {
    return [
      {
        file: SHEET,
        check: "rendered-verdict",
        message:
          `the case renders ${String(ROW_COUNT)} offer rows and the panel drew ` +
          `${String(report.rows.length)}, so there is no fourth row whose clipped edge could be the scroll affordance.`,
      },
    ];
  }

  const fourth = report.rows.at(-1)!;
  const topInside = fourth.topPx < report.panelBottomPx - CLIP_TOLERANCE_PX;
  const bottomClipped = fourth.bottomPx > report.panelBottomPx + CLIP_TOLERANCE_PX;
  if (topInside && bottomClipped) return [];

  const seen =
    `the fourth row spans ${fourth.topPx.toFixed(2)}px to ${fourth.bottomPx.toFixed(2)}px and the panel's clip ` +
    `sits at ${report.panelBottomPx.toFixed(2)}px`;
  return [
    {
      file: SHEET,
      check: "rendered-verdict-affordance",
      message: !topInside
        ? `no clipped edge shows: ${seen}. The fourth row's TOP EDGE has to sit inside the panel, and at this ` +
          "rendering it lies wholly below the clip -- the reserved height no longer reaches into the fourth row, " +
          "which is what a `--verdict-h` shortened until the held rows fill the panel does."
        : `nothing is left to reveal: ${seen}. The fourth row's BOTTOM EDGE has to lie beyond the panel's clip, ` +
          "and at this rendering it fits inside -- the panel holds every row whole, so no reader can see that the " +
          "rows scroll, which is what growing `--verdict-h` to fit them does.",
    },
  ];
}
