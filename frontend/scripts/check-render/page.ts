/* THE PROBE PAGE, BUILT FROM THE MARKUP THE COMPONENT EMITS AND THE STYLESHEET A BROWSER GETS.
 *
 * Three things make this a measurement rather than an imitation.
 *
 * THE MARKUP is the one `Block.tsx` writes, and `src/ui/domain/week-grid/__tests__/probe.test.tsx` renders the real
 * component and requires this page to carry every class, every nested element, every attribute and the same block
 * height and line count. That copy is always one edit away from drifting, and a drifted probe measures a shape the
 * product does not ship.
 *
 * THE ARITHMETIC IS RESTATED HERE AND HELD AGAINST THE DOMAIN'S, which is the one shape available across this
 * boundary. `tiers.ts` and `geometry.ts` import `./metrics` without an extension, because a bundler resolves the
 * application's own imports; the runtime a SCRIPT runs under does not, so a script cannot import either module at all.
 * `metrics.ts` is import-free and therefore reachable, so the constants are the domain's and only the three formulas
 * are second copies.
 *
 * What holds them is `__tests__/pixels.test.ts`, which runs under the bundler and can import both sides: it sweeps a
 * range of heights and requires this file's `linesOf`, `tierOf` and `heightOf` to agree with `titleLineCount`,
 * `tierFor` and `pxPerMinute` at every one. That pins BOTH directions, where literals in a test pinned only the probe:
 * a change to the ladder reddens here as well as in the ladder's own test, so the probe cannot silently keep measuring
 * a line count the product never sets. The modal block is exactly the case a mis-calibrated probe would stop covering.
 *
 * THE SHEET IS THE BUILT BUNDLE, not the component's own file: the block is a `<button>`, and its zero right edge
 * comes from Tailwind's preflight reset, which only the bundle carries. A probe linking `block.css` alone measures a
 * user-agent button and reports a right border that never ships.
 *
 * EACH CASE IS RENDERED THREE TIMES. Capped at the line count its height yields; UNCAPPED, which is the control for
 * anything the cap itself does; and once in a column wide enough that no truncation is possible at all, which is the
 * control for anything the RULE does. Two controls, because one of them cannot see a defect that changes both copies
 * equally: `white-space: nowrap` with `text-overflow: ellipsis` truncates the capped and uncapped copies alike and
 * cancels out of their comparison. `check.ts` states which comparison proves what.
 *
 * THE TWO COLUMNS ARE STACKED RATHER THAN SIDE BY SIDE. Beside each other they are two flex items, a flex item
 * shrinks, and the narrow column collapsed to 14px: every region then read pixels belonging to nothing. Stacked, each
 * container keeps its declared width and every region's Y is a figure this file computes.
 *
 * BELOW BOTH OF THEM THE WEEK'S SEVEN DAY COLUMNS ARE LAID OUT SIDE BY SIDE, which is the one thing on this page that
 * has to be. They carry no block and no title: what they are here for is seven boxes a browser computed, so the drag's
 * own pointer read can be asked what a position over one column names against the box of the one beside it.
 * `weekColumns.ts` owns them. */

/* `metrics.ts` is import-free, so a script can read it. Its siblings import `./metrics` without an extension and are
 * therefore unreachable here, which is why the three formulas below are restated and asserted rather than imported. */
import {
  AREA_RULE_PX,
  BLOCK_H_COMPACT_PX,
  BLOCK_H_LABEL_PX,
  BLOCK_H_SLIVER_PX,
  BLOCK_PAD_T_PX,
  BOTTOM_RULE_PX,
  GRID_H_PX,
  LINE_HEIGHT_PX,
  VISIBLE_HOURS_DEFAULT,
} from "../../src/ui/domain/week-grid/metrics.ts";
import { COLUMN_READINGS_ID, weekColumns } from "./weekColumns.ts";
import { LINE_READINGS_ID, lineWeightSection } from "./lineWeight.ts";
import { VERDICT_READINGS_ID, VERDICT_SECTION } from "./verdictPanel.ts";

/** The narrowest supported day column, `--col-min`, which is where a title is tightest. */
export const COLUMN_PX = 137;

/** Wide enough that no title here wraps or truncates, so its first line is the untruncated one. */
export const WIDE_COLUMN_PX = 900;

/** How far apart the renderings of one case are placed, so no case's clipping reaches another.
 *
 * RAISED ABOVE THE VERDICT PANEL'S RESERVED HEIGHT, which is `--verdict-h` in the domain's own tokens (226px),
 * because the slot this figure sizes below the columns is where the rendered verdict panel stands
 * (`verdictPanel.ts`): a pitch at or under the panel's height would push the panel's lower edge past the window
 * this page is shot at, and the gate would read a panel the product does not fully draw. Raising the pitch keeps
 * every existing region where its arithmetic put it; widening the window another way would move them all. */
const CASE_PITCH_PX = 230;

/** Air around the widest thing the page holds, so nothing sits against the window's own edge. */
const PAGE_MARGIN_PX = 40;

/** The uncapped control's own line allowance: more lines than any title here needs. */
const UNCAPPED_LINES = 99;

/** The block states a case stands in, all absent at rest. `BlockStates`' own spelling. */
export interface RenderStates {
  readonly selected?: boolean | undefined;
  readonly conflicted?: boolean | undefined;
  readonly proposalTarget?: boolean | undefined;
  /** A block divided by a deeper stagger, which owns the one hairline left rule at rest. */
  readonly split?: boolean | undefined;
}

export interface RenderCase {
  readonly name: string;
  readonly title: string;
  /** Minutes the block runs for, from which its height and its line count follow. */
  readonly durationMinutes: number;
  /** Visible hours, so a case can name the zoom it is measured at. */
  readonly visibleHours: number;
  /** What sits in the glyph slot, or none. A float shortens the lines it overlaps and nothing else. */
  readonly glyph?: "pinned" | "overlap" | undefined;
  /** What the time is. Absent means a task of an Area; an anchor carries the hatch instead. */
  readonly origin?: "task" | "anchor" | undefined;
  /** The states the case renders with, absent at rest. */
  readonly states?: RenderStates | undefined;
}

/**
 * The cases, and why each is here.
 *
 * The first three are the design record's own measured ledger: three titles sharing a prefix and differing only in
 * the tail, at the MODAL thirty-minute duration on the reference display at the default zoom. That is the common
 * case, not an edge, and it is where an end-ellipsis collapsed all three to one string.
 *
 * The last three exercise the gate's own arithmetic and the layout the fix touched. A four-hour block caps at
 * FOURTEEN lines, which is past the point where an unbounded comparison used to read the copy below it. A pinned
 * block and a staggered one carry a glyph, and the float that puts it beside a wrapping title is the reason the
 * block became a column flex box with one block child: with a glyph the first line box goes from 110.78px to
 * 41.55px, so a case with an empty slot never measures it.
 *
 * THE STATE CASES turn the channel table into measurements. Each composition rule the sheets state about the left
 * rule, the fill and the hatch is asserted by `check.ts` over what a browser computed for one of these: conflict
 * winning the left rule over selected, the split's hairline REPLACED by the state rule rather than added to it,
 * the proposal target keeping the Area's top rule while giving up its fill, and the anchor's hatch riding the
 * image channel so hover's colour composes with it rather than competing.
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
  {
    name: "four-hour block, fourteen lines",
    title:
      "Leetcode - Graphs, Dynamic Programming, Trees, Heaps and every other topic this session covers before it ends",
    durationMinutes: 240,
    visibleHours: 12,
  },
  {
    name: "pinned modal block, the glyph shortening its first line",
    title: "Amazon Interview Prep - Behavioral",
    durationMinutes: 30,
    visibleHours: 12,
    glyph: "pinned",
  },
  {
    name: "staggered block, the count marker shortening its first line",
    title: "Amazon Interview Prep - Behavioral",
    durationMinutes: 90,
    visibleHours: 12,
    glyph: "overlap",
  },
  {
    name: "conflicted and selected, the conflict winning the left rule",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
    states: { conflicted: true, selected: true },
  },
  {
    name: "conflicted alone, the left rule in oxide",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
    states: { conflicted: true },
  },
  {
    name: "selected alone, the reserved rule inked",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
    states: { selected: true },
  },
  {
    name: "split at rest, its own hairline left rule",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
    states: { split: true },
  },
  {
    name: "split and selected, the state rule replacing the split's",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
    states: { split: true, selected: true },
  },
  {
    name: "proposal target, no fill and the Area's top rule kept",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
    states: { proposalTarget: true },
  },
  {
    name: "anchor block, the hatch over the fill",
    title: "Amazon Interview Prep",
    durationMinutes: 30,
    visibleHours: 12,
    origin: "anchor",
  },
];

export interface CaseGeometry extends RenderCase {
  readonly heightPx: number;
  readonly lines: number;
  readonly tier: string;
  /** Where the capped copy sits on the page. */
  readonly cappedTopPx: number;
  /** Where the uncapped control sits. */
  readonly uncappedTopPx: number;
  /** Where the untruncatable control sits, in its own wide column. */
  readonly widePx: number;
  /** The title's expected top offset inside the block: the Area rule, plus the padding the tier keeps. */
  readonly titleTopPx: number;
}

/** How tall a block of this duration is at this zoom on the reference display, unmeasured. `pxPerMinute`'s formula. */
export function heightOf(durationMinutes: number, visibleHours: number): number {
  return durationMinutes * (GRID_H_PX / (visibleHours * 60));
}

/** The tier a height lands in. `tierFor`'s ladder. */
export function tierOf(heightPx: number): string {
  if (heightPx >= BLOCK_H_LABEL_PX) return "label";
  if (heightPx >= BLOCK_H_COMPACT_PX) return "compact";
  if (heightPx >= BLOCK_H_SLIVER_PX) return "sliver";
  return "hairline";
}

/** How many lines of title a height holds. `titleLineCount`'s arithmetic. */
export function linesOf(heightPx: number): number {
  const tier = tierOf(heightPx);
  if (tier === "sliver" || tier === "hairline") return 0;
  if (tier === "compact") return 1;
  return Math.max(
    1,
    Math.floor((heightPx - (AREA_RULE_PX + BLOCK_PAD_T_PX + BOTTOM_RULE_PX)) / LINE_HEIGHT_PX),
  );
}

export function geometryOf(cases: readonly RenderCase[]): CaseGeometry[] {
  return cases.map((each, index) => {
    const heightPx = heightOf(each.durationMinutes, each.visibleHours);
    const tier = tierOf(heightPx);
    return {
      ...each,
      heightPx,
      lines: linesOf(heightPx),
      tier,
      cappedTopPx: index * CASE_PITCH_PX,
      uncappedTopPx: index * CASE_PITCH_PX + CASE_PITCH_PX / 2,
      /* One full pitch per case below the narrow column, which is where the stacked wide column begins. */
      widePx: cases.length * CASE_PITCH_PX + index * CASE_PITCH_PX,
      titleTopPx: tier === "compact" ? AREA_RULE_PX : AREA_RULE_PX + BLOCK_PAD_T_PX,
    };
  });
}

/* The glyph slot's own markup, which is `GlyphSlot`'s: a class from the kit's table and a count where it carries one.
 * Written rather than imported because this page reaches a browser as text. */
function glyphSlot(claim: RenderCase["glyph"]): string {
  if (claim === undefined) return `<span class="week-block__glyph"></span>`;
  const mark = claim === "pinned" ? "glyph--pinned" : "glyph--overlap";
  const count = claim === "overlap" ? "5" : "";
  return (
    `<span class="week-block__glyph">` +
    `<span class="glyph glyph-slot ${mark}" aria-hidden="true">${count}</span>` +
    `</span>`
  );
}

/* An empty-string data attribute when the state holds, absent otherwise, which is what React writes. */
function flag(name: string, on: boolean | undefined): string {
  return on === true ? ` ${name}=""` : "";
}

/* The class list, the attributes and the inline style `Block.tsx` writes, in the NESTING it writes them in: the glyph
 * and the title are both inside `__body`, because the float that puts one beside the other cannot live in the flex
 * container the block itself is. Emitting the glyph as a sibling of `__body` makes it a flex ITEM, which pushes the
 * title 17.80px down: the gate caught exactly that the first time a case carried a glyph. The anchor's hatch sits
 * before `__body` for the same reason: it is absolutely positioned, but the ORDER is what the component writes. */
function block(geometry: CaseGeometry, lines: number, topPx: number, id: string): string {
  const states = geometry.states ?? {};
  return (
    `<button type="button" id="${id}" class="week-block week-block--area-01 state-row"` +
    flag("data-conflict", states.conflicted) +
    flag("data-pinned", geometry.glyph === "pinned") +
    flag("data-proposal", states.proposalTarget) +
    flag("data-selected", states.selected) +
    flag("data-split", states.split) +
    ` data-origin="${geometry.origin ?? "task"}" data-tier="${geometry.tier}"` +
    ` aria-label="${geometry.title} \u00b7 Career"` +
    ` style="top:${String(topPx)}px;height:${geometry.heightPx.toFixed(3)}px` +
    `;left:calc(var(--grid-inset) + 0.000%);right:calc(var(--grid-inset) + 0.000%)` +
    `;z-index:0;--lines:${String(lines)}">` +
    (geometry.origin === "anchor"
      ? `<span aria-hidden="true" class="week-block__hatch"></span>`
      : "") +
    `<span class="week-block__body">` +
    glyphSlot(geometry.glyph) +
    `<span class="week-block__title">${geometry.title}</span>` +
    `</span></button>`
  );
}

export interface PageRequest {
  /** The name the built stylesheet is written under, beside the page, so the link is relative. */
  readonly bundleName: string;
  readonly cases: readonly CaseGeometry[];
  /** The name the compiled pointer read is written under, or absent where compiling it failed. */
  readonly scriptName?: string | undefined;
}

/* The seven day columns, at the default zoom on the reference display, which is where the title cases are measured
 * too. `weekColumns` owns everything about them; the page places the section and links the script. */
export const WEEK_SECTION = weekColumns({
  pxPerMin: heightOf(1, VISIBLE_HOURS_DEFAULT),
  columnPx: COLUMN_PX,
});

/** One canvas of grid lines, drawn at rest so the reading can step it to dragging. `lineWeight` owns it. */
export const LINES_SECTION = lineWeightSection();

/** How wide a window has to be to hold the widest thing on the page, which is the week's seven columns. */
export const PAGE_WIDTH_PX = Math.max(WIDE_COLUMN_PX, WEEK_SECTION.widthPx) + PAGE_MARGIN_PX;

/** The channel the page reports each block's own geometry on. */
export const READINGS_ID = "readings";

/** The element id of one case's rendering, so an in-page reading can name what it measured. */
export function idOf(index: number, copy: "capped" | "uncapped" | "wide"): string {
  return `${copy}-${String(index)}`;
}

/** What the page reports about itself, which is the geometry a screenshot cannot show. */
export interface PageReading {
  readonly id: string;
  /** The title's top edge, in pixels below the block's own top edge. */
  readonly titleTopPx: number;
  /** The title's left edge, likewise, which is where the prefix comparison starts reading. */
  readonly titleLeftPx: number;
  readonly lineHeightPx: number;
  readonly maxHeightPx: number;
  /** The first line box's width, which the glyph's float shortens where there is one. */
  readonly firstLineWidthPx: number;
  /* THE FOUR EDGES AS THE BROWSER COMPOSED THEM, widths and inks off the BLOCK element. These are the channel
   * table's readings: what a state won, replaced or kept is answered here and not by any declaration. */
  readonly borderTopWidth: string;
  readonly borderTopColor: string;
  readonly borderRightWidth: string;
  readonly borderRightColor: string;
  readonly borderBottomWidth: string;
  readonly borderBottomColor: string;
  readonly borderBottomStyle: string;
  readonly borderLeftWidth: string;
  readonly borderLeftColor: string;
  /** The block's own fill, which the proposal target gives up and hover recolours. */
  readonly backgroundColor: string;
  /** The anchor hatch's painted image, or null where the block carries no hatch. */
  readonly hatchBackgroundImage: string | null;
}

export function probePage({ bundleName, cases, scriptName }: PageRequest): string {
  const narrow = cases
    .flatMap((each, index) => [
      block(each, each.lines, each.cappedTopPx, idOf(index, "capped")),
      block(each, UNCAPPED_LINES, each.uncappedTopPx, idOf(index, "uncapped")),
    ])
    .join("\n");
  const wide = cases
    .map((each, index) =>
      block(each, UNCAPPED_LINES, each.widePx - stackTopPx(cases), idOf(index, "wide")),
    )
    .join("\n");

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>week-grid rendered probe</title>
<link rel="stylesheet" href="./${bundleName}">
<style>
  body { margin: 0; background: #fff }
  /* STACKED, NOT SIDE BY SIDE. Two columns beside each other are two flex items, and a flex item shrinks: the narrow
     column collapsed and every region read the wrong pixels. Stacking keeps each container at its declared width and
     makes every region's Y a figure this file computes rather than one the layout negotiates. */
  #column { position: relative; width: ${String(COLUMN_PX)}px; background: var(--paper-raised) }
  #wide { position: relative; width: ${String(WIDE_COLUMN_PX)}px; background: var(--paper-raised) }
  ${VERDICT_SECTION.style}
  ${WEEK_SECTION.style}
</style></head>
<body>
<div id="column" style="height:${String(stackTopPx(cases))}px">
${narrow}
</div>
<div id="wide" style="height:${String(stackTopPx(cases))}px">
${wide}
</div>
${VERDICT_SECTION.html}
${WEEK_SECTION.html}
${LINES_SECTION.html}
<pre id="${READINGS_ID}"></pre>
<pre id="${COLUMN_READINGS_ID}"></pre>
<pre id="${LINE_READINGS_ID}"></pre>
<pre id="${VERDICT_READINGS_ID}"></pre>
${scriptName === undefined ? "" : `<script src="./${scriptName}"></script>`}
<script>
  const readings = [...document.querySelectorAll(".week-block")].map((block) => {
    const title = block.querySelector(".week-block__title");
    const style = getComputedStyle(title);
    const composed = getComputedStyle(block);
    const hatch = block.querySelector(".week-block__hatch");
    return {
      id: block.id,
      titleTopPx: title.getBoundingClientRect().top - block.getBoundingClientRect().top,
      titleLeftPx: title.getBoundingClientRect().left - block.getBoundingClientRect().left,
      lineHeightPx: Number.parseFloat(style.lineHeight),
      maxHeightPx: Number.parseFloat(style.maxHeight),
      firstLineWidthPx: title.getBoundingClientRect().width,
      borderTopWidth: composed.borderTopWidth,
      borderTopColor: composed.borderTopColor,
      borderRightWidth: composed.borderRightWidth,
      borderRightColor: composed.borderRightColor,
      borderBottomWidth: composed.borderBottomWidth,
      borderBottomColor: composed.borderBottomColor,
      borderBottomStyle: composed.borderBottomStyle,
      borderLeftWidth: composed.borderLeftWidth,
      borderLeftColor: composed.borderLeftColor,
      backgroundColor: composed.backgroundColor,
      hatchBackgroundImage:
        hatch === null ? null : getComputedStyle(hatch).backgroundImage,
    };
  });
  document.getElementById(${JSON.stringify(READINGS_ID)}).textContent = JSON.stringify(readings);
</script>
<script>${WEEK_SECTION.script}</script>
<script>${LINES_SECTION.script}</script>
<script>${VERDICT_SECTION.script}</script>
</body></html>
`;
}

/** Where the wide column begins, which is one full pitch per case below the narrow one. */
export function stackTopPx(cases: readonly CaseGeometry[]): number {
  return cases.length * CASE_PITCH_PX;
}

/** How tall a window has to be to hold both columns, the week, the verdict section and the line-weight section,
 * so no region reads past the screenshot. */
export function pageHeightPx(cases: readonly CaseGeometry[]): number {
  return Math.ceil(
    2 * stackTopPx(cases) + CASE_PITCH_PX + WEEK_SECTION.heightPx + LINES_SECTION.heightPx,
  );
}

export const PAGE_PITCH_PX = CASE_PITCH_PX;
export const UNCAPPED_LINE_ALLOWANCE = UNCAPPED_LINES;
