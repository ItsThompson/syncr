/* THE PROBE PAGE, BUILT FROM THE MARKUP THE COMPONENT ACTUALLY EMITS AND THE STYLESHEET A BROWSER ACTUALLY GETS.
 *
 * Two things make this a measurement rather than an imitation. The class list, the data attributes and the inline
 * style are the ones `Block.tsx` writes, and `__tests__/rendered.test.ts` asserts that by rendering the real
 * component and comparing. And the sheet is the BUILT bundle, not the component's own file: the block is a
 * `<button>`, and its zero right edge comes from Tailwind's preflight reset, which only the bundle carries. A probe
 * linking `block.css` alone measures a user-agent button and reports a right border that does not ship.
 *
 * EACH CASE IS RENDERED TWICE, once at the line count its own height yields and once with no cap at all. The
 * uncapped copy is the control: whatever the capped one shows over those line boxes has to be identical to it. An
 * ellipsis is ink the control does not have, and a mid-glyph clip is ink the control has more of. Neither can hide
 * behind a declaration. */

import {
  AREA_RULE_PX,
  BLOCK_PAD_T_PX,
  GRID_H_PX,
  LINE_HEIGHT_PX,
} from "../../src/ui/domain/week-grid/metrics.ts";

/** The narrowest supported day column, `--col-min`, which is where a title is tightest. */
export const COLUMN_PX = 137;

/** How far apart the two renderings of one case are placed, so neither's clipping reaches the other. */
const CASE_PITCH_PX = 220;

/** The uncapped control's own line allowance: more lines than any title here needs. */
const UNCAPPED_LINES = 99;

export interface RenderCase {
  readonly name: string;
  readonly title: string;
  /** Minutes the block runs for, from which its height and its line count follow. */
  readonly durationMinutes: number;
  /** Visible hours, so a case can name the zoom it is measured at. */
  readonly visibleHours: number;
}

/**
 * The cases, and why each is here.
 *
 * The first three are the design record's own measured ledger: three titles that share a prefix and differ only in
 * the tail, at the MODAL thirty-minute duration on the reference display at the default zoom. That is the common
 * case, not an edge, and it is where an end-ellipsis collapses all three to one string.
 */
export const CASES: readonly RenderCase[] = [
  {
    name: "modal block, one line",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
  },
  {
    name: "modal block, one line, a longer tail",
    title: "Amazon Interview Prep - Behavioral",
    durationMinutes: 30,
    visibleHours: 12,
  },
  {
    name: "modal block, one line, a different tail",
    title: "Amazon Interview Prep - System Design",
    durationMinutes: 30,
    visibleHours: 12,
  },
  {
    name: "ninety-minute block, several lines",
    title: "Amazon Interview Prep - Behavioral",
    durationMinutes: 90,
    visibleHours: 12,
  },
  {
    name: "sixty-minute block at the deepest zoom",
    title: "Visual Computing Lecture and the rest of its name",
    durationMinutes: 60,
    visibleHours: 24,
  },
  {
    name: "compact tier, one line at the smaller size",
    title: "Wake Up before the alarm",
    durationMinutes: 15,
    visibleHours: 12,
  },
];

export interface CaseGeometry extends RenderCase {
  readonly heightPx: number;
  readonly lines: number;
  /** Where the capped copy sits on the page. */
  readonly cappedTopPx: number;
  /** Where the uncapped control sits. */
  readonly uncappedTopPx: number;
}

/** How tall a block of this duration is at this zoom on the reference display, unmeasured. */
export function heightOf(durationMinutes: number, visibleHours: number): number {
  return durationMinutes * (GRID_H_PX / (visibleHours * 60));
}

/** How many lines of title that height holds, which is `tiers.ts`'s arithmetic. */
export function linesOf(heightPx: number): number {
  const chrome = AREA_RULE_PX + BLOCK_PAD_T_PX + 1;
  if (heightPx < 13) return 0;
  if (heightPx < 19) return 1;
  return Math.max(1, Math.floor((heightPx - chrome) / LINE_HEIGHT_PX));
}

export function geometryOf(cases: readonly RenderCase[]): CaseGeometry[] {
  return cases.map((each, index) => {
    const heightPx = heightOf(each.durationMinutes, each.visibleHours);
    return {
      ...each,
      heightPx,
      lines: linesOf(heightPx),
      cappedTopPx: index * CASE_PITCH_PX,
      uncappedTopPx: index * CASE_PITCH_PX + CASE_PITCH_PX / 2,
    };
  });
}

/** The tier attribute a height lands in, which is what drives the type size and the padding. */
function tierOf(heightPx: number): string {
  if (heightPx >= 19) return "label";
  if (heightPx >= 13) return "compact";
  if (heightPx >= 8) return "sliver";
  return "hairline";
}

/* The class list, the attributes and the inline style `Block.tsx` writes. Held against the real component by
 * `__tests__/rendered.test.ts`, so this cannot drift into an imitation of it. */
function block(geometry: CaseGeometry, lines: number, topPx: number): string {
  return (
    `<button type="button" class="week-block week-block--area-01 state-row"` +
    ` data-origin="task" data-tier="${tierOf(geometry.heightPx)}"` +
    ` aria-label="${geometry.title} \u00b7 Career"` +
    ` style="top:${topPx}px;height:${geometry.heightPx.toFixed(3)}px` +
    `;left:calc(var(--grid-inset) + 0.000%);right:calc(var(--grid-inset) + 0.000%)` +
    `;z-index:0;--lines:${lines}">` +
    `<span class="week-block__body">` +
    `<span class="week-block__glyph"></span>` +
    `<span class="week-block__title">${geometry.title}</span>` +
    `</span></button>`
  );
}

export interface PageRequest {
  /** The name the built stylesheet is written under, beside the page, so the link is relative. */
  readonly bundleName: string;
  readonly cases: readonly CaseGeometry[];
}

export function probePage({ bundleName, cases }: PageRequest): string {
  const blocks = cases
    .flatMap((each) => [
      block(each, each.lines, each.cappedTopPx),
      block(each, UNCAPPED_LINES, each.uncappedTopPx),
    ])
    .join("\n");

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>week-grid rendered probe</title>
<link rel="stylesheet" href="./${bundleName}">
<style>
  body { margin: 0; background: #fff }
  /* One column at --col-min, the narrowest a day column is allowed to be, which is where a title is tightest. */
  #column { position: relative; width: ${COLUMN_PX}px; background: var(--paper-raised) }
</style></head>
<body><div id="column" style="height:${cases.length * CASE_PITCH_PX}px">
${blocks}
</div></body></html>
`;
}

export const PAGE_PITCH_PX = CASE_PITCH_PX;
export const UNCAPPED_LINE_ALLOWANCE = UNCAPPED_LINES;
