/* THE CHECK, AND WHAT EACH OF ITS THREE COMPARISONS ACTUALLY PROVES.
 *
 * A CAPPED TITLE SHOWS THE SAME PIXELS AS AN UNCAPPED ONE over the lines it keeps. That is both halves of the
 * criterion for anything the CAP does: an end-ellipsis the cap supplies is ink the control does not have, and a clip
 * landing mid-glyph is ink the control has more of.
 *
 * IT CANNOT SEE A TRUNCATION THAT ALSO HITS THE CONTROL, and that limit is the reason for the second comparison. The
 * uncapped control is the same rule at a large line allowance, so anything the RULE truncates truncates in both copies
 * and cancels: `white-space: nowrap` with `text-overflow: ellipsis` renders an end-ellipsis on every case and that
 * comparison alone reports nothing. So each case is also rendered in a column wide enough that no truncation is
 * possible, and the capped copy's first line must be a pixel PREFIX of it. That catches the class the first comparison
 * cancels.
 *
 * THE DECLARATION SWEEP REMAINS LOAD-BEARING EITHER WAY, and not as a formality: `blockStylesheet.test.ts` refuses
 * `line-clamp`, `block-ellipsis`, `text-overflow` and `white-space` by name across every sheet in the family, and it
 * catches the class this gate's own control cancels. Both layers are armed now -- this one runs in
 * `just lint-frontend` -- and they are complementary rather than redundant: a reader who retires the declaration
 * guards believing this one subsumes them would be retiring the net that sees a truncation applying to every copy.
 *
 * THE TITLE'S TOP OFFSET is the third reading, and it is a geometry question rather than a pixel one. It is here
 * because a `<button>` centres its content, which put a two-line title 26.70px from its block's top instead of 4px:
 * the pixel comparisons catch that only as a side effect, on the wrong cases, so the figure is asserted directly.
 *
 * THE FOURTH READING IS THE ONLY ONE THAT IS NOT ABOUT A TITLE. Seven day columns are laid out beside each other and
 * the drag's own pointer read is asked what a position over one of them names against the box of the column beside it.
 * That question has no answer anywhere else in this repository: the read takes one box, the box comes from
 * `getBoundingClientRect`, and jsdom answers it with whatever a test stubbed -- one rectangle for every canvas, which
 * puts "over the next column" inside the origin column too. `horizontalRead.ts` states what each of its findings is
 * about, and they fail apart so a page that could not measure is never mistaken for a drag that placed a block in a
 * day the reader had left.
 *
 * A MISSING BROWSER IS A FINDING. A check that passes when it cannot look reports a claim it never tested. */

import path from "node:path";

import { AREA_RULE_PX, LINE_HEIGHT_PX } from "../../src/ui/domain/week-grid/metrics.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { BROWSER_ENV, findBrowser, screenshot } from "./browser.ts";
import { buildDragRead, DRAG_READ_SCRIPT } from "./dragRead.ts";
import { horizontalRead } from "./horizontalRead.ts";
import { LINE_READINGS_ID, type LineWeightReading } from "./lineWeight.ts";
import { frontendRoot } from "../lib/paths.ts";
import { differencesBetween, imageOf, lastInkedColumn, sketch, type Region } from "./pixels.ts";
import {
  CASES,
  COLUMN_PX,
  geometryOf,
  idOf,
  PAGE_PITCH_PX,
  PAGE_WIDTH_PX,
  pageHeightPx,
  probePage,
  READINGS_ID,
  WIDE_COLUMN_PX,
  type CaseGeometry,
  type PageReading,
  type RenderCase,
} from "./page.ts";
import { COLUMN_READINGS_ID } from "./weekColumns.ts";
import { parseVerdictReport, VERDICT_READINGS_ID, verdictFindings } from "./verdictPanel.ts";

export interface CheckRenderInput {
  /** The built stylesheet a browser downloads, by name and content, from the build the bundle gate reads. */
  readonly bundleName: string;
  readonly css: string;
}

/** How many rows of a sketch a finding carries, so the reader sees the line the difference lands in. */
const SKETCH_ROWS = 14;

/** How far a measured offset may sit from the arithmetic before it is a finding. Sub-pixel rounding, nothing more. */
const OFFSET_TOLERANCE_PX = 0.5;

/* THE CHANNEL TABLE'S OWN FIGURES, mirrored from the tokens that draw them.
 *
 * `--state-selected-border` and `--state-conflict-border`, the weight both state rules share; and `--hairline`,
 * the split rule's own weight, which a state rule replaces rather than adds to. Absolute figures here are what the
 * composition rules name; WHICH ink wins is asserted relatively, between cases, so a retuned pigment cannot stale
 * this gate. */
const STATE_RULE_PX = "3px";
const HAIRLINE_PX = "1px";
/** What Chromium computes for an absent fill or a transparent rule colour. */
const TRANSPARENT = "rgba(0, 0, 0, 0)";

const SHEET = path.join("frontend", "src", "ui", "domain", "week-grid", "block.css");

export async function checkRender({ bundleName, css }: CheckRenderInput): Promise<CheckOutcome> {
  const browser = await findBrowser();
  if (browser === null) {
    return {
      findings: [
        {
          file: path.join("frontend", "scripts", "check-render", "browser.ts"),
          check: "no-browser",
          message:
            "no headless Chromium was found, so nothing rendered and nothing was measured. This is the one " +
            `gate that looks at a pixel; point ${BROWSER_ENV} at a browser rather than letting it pass unlooked.`,
        },
      ],
      notes: [],
    };
  }

  const cases = geometryOf(CASES);
  const compiled = await compiledRead();
  const shot = await screenshot({
    browser,
    html: probePage({
      bundleName,
      cases,
      ...(compiled.code === null ? {} : { scriptName: DRAG_READ_SCRIPT }),
    }),
    beside: {
      [bundleName]: css,
      ...(compiled.code === null ? {} : { [DRAG_READ_SCRIPT]: compiled.code }),
    },
    widthPx: PAGE_WIDTH_PX,
    heightPx: pageHeightPx(cases),
  });
  const image = imageOf(shot.png);
  const readings = parseReadings(shot.readings[READINGS_ID] ?? "");
  const columns = horizontalRead(shot.readings[COLUMN_READINGS_ID] ?? "");
  const weights = parseLineWeights(shot.readings[LINE_READINGS_ID] ?? "");
  const verdict = parseVerdictReport(shot.readings[VERDICT_READINGS_ID] ?? "");

  const findings: Finding[] = [
    ...compiled.findings,
    ...columns.findings,
    ...channelTable(cases, readings),
    ...lineWeightFindings(weights),
    ...verdictFindings(verdict),
  ];
  for (const [index, each] of cases.entries()) {
    findings.push(...cappedAgainstUncapped(image, each));
    if (!paintsBoxSizedTexture(each)) {
      findings.push(...cappedAgainstUntruncatable(image, each, index, readings));
    }
    findings.push(...topOffsetOf(each, index, readings));
  }

  return {
    findings,
    notes: [
      `${path.basename(browser)}, ${bundleName}`,
      `${String(cases.length)} case(s), each rendered capped, uncapped and untruncatable`,
      ...cases.map(
        (each) =>
          `  ${each.name}: ${String(each.durationMinutes)}m at ${String(each.visibleHours)}h is ` +
          `${each.heightPx.toFixed(3)}px, ${each.tier} tier, ${String(each.lines)} line(s)`,
      ),
      ...channelNotes(cases, readings),
      ...columns.notes,
      ...verdictNotes(verdict),
    ],
  };
}

/* THE SHIPPED POINTER READ, OR THE REASON THERE IS NONE. A build that failed is a fault in this gate and it is
 * reported as one: the page then reports that it loaded no read, and neither is mistaken for a drag that placed a
 * block in the wrong day. */
async function compiledRead(): Promise<{ code: string | null; findings: Finding[] }> {
  try {
    return { code: await buildDragRead(), findings: [] };
  } catch (failure) {
    return {
      code: null,
      findings: [
        {
          file: path.join(frontendRoot, "scripts", "check-render", "dragRead.ts"),
          check: "column-readings",
          message:
            "the drag's own pointer read did not compile, so the page could not be asked what a position over the " +
            `next column names: ${failure instanceof Error ? failure.message : String(failure)}`,
        },
      ],
    };
  }
}

/* Where one case's copies sit. The geometry already carries each top, so the copy's NAME is all this needs. */
function regionOf(copy: "capped" | "uncapped" | "wide", each: CaseGeometry): Region {
  if (copy === "wide") {
    return { xPx: 0, widthPx: WIDE_COLUMN_PX, topPx: each.widePx, heightPx: PAGE_PITCH_PX / 2 };
  }
  const topPx = copy === "capped" ? each.cappedTopPx : each.uncappedTopPx;
  return { xPx: 0, widthPx: COLUMN_PX, topPx, heightPx: PAGE_PITCH_PX / 2 };
}

/** The rows one case's capped copy shows, never more than the region holding it. */
function depthOf(each: CaseGeometry): number {
  return Math.min(Math.ceil(each.lines * LINE_HEIGHT_PX), PAGE_PITCH_PX / 2);
}

/* WHAT THE CAP DOES. Identical over the lines the capped copy keeps, or the cap added or removed ink. */
function cappedAgainstUncapped(image: ReturnType<typeof imageOf>, each: CaseGeometry): Finding[] {
  const capped = regionOf("capped", each);
  const uncapped = regionOf("uncapped", each);
  const differences = differencesBetween(image, capped, uncapped, depthOf(each));
  if (differences.length === 0) return [];

  const total = differences.reduce((sum, row) => sum + row.differingPixels, 0);
  return [
    {
      file: SHEET,
      check: "rendered-title",
      message:
        `${each.name}: the title capped at ${String(each.lines)} line(s) renders ${String(total)} pixel(s) ` +
        `differently from the same title uncapped, over the ${String(each.lines)} line(s) it shows. A cap adds ` +
        "nothing and removes nothing inside the lines it keeps, so a difference is an end-ellipsis the cap " +
        `supplied or a clip landing mid-glyph. Title: ${JSON.stringify(each.title)}.\n` +
        `        capped:\n${indent(sketch(image, capped, SKETCH_ROWS))}\n` +
        `        uncapped:\n${indent(sketch(image, uncapped, SKETCH_ROWS))}`,
    },
  ];
}

/* Whether a case paints a texture whose phase follows its own box. An angled repeating gradient is laid out along
 * a gradient line derived from the box's width and height, so the SAME hatch renders at a different phase in the
 * 900px control than in the 137px column and every row differs by antialiasing alone. Such a case carries no
 * truncation information across the width boundary, so it sits out of the prefix comparison; its channels are
 * still measured by the channel table, and its capped and uncapped copies, which share one column and one phase,
 * are still compared above. */
function paintsBoxSizedTexture(each: CaseGeometry): boolean {
  return each.origin === "anchor";
}

/* WHAT THE RULE DOES. The capped copy's first line has to be a pixel PREFIX of the same title where nothing can
 * truncate at all, which is the comparison the uncapped control cancels.
 *
 * READ FROM THE TITLE'S OWN BOX, NOT THE BLOCK'S. Anchoring on the region's first ink anchors on the block's top
 * BORDER, whose last inked column is the far edge of the block: the first draft therefore compared a border row and
 * reported the whole line. The page reports where the title sits, so the comparison starts there.
 *
 * AND READ ONLY AS FAR AS THE TEXT REACHES. Two bounds, both needed. The glyph FLOATS at the right of the first line,
 * so the line is not a pure prefix past the title's box, and the box's own width, which the page reports and which the
 * float shortens, is the outer bound. The text usually ends before the box does, so the rightmost ink inside that
 * bound is the inner one. Past it the wide copy legitimately continues with the rest of the title. */
function cappedAgainstUntruncatable(
  image: ReturnType<typeof imageOf>,
  each: CaseGeometry,
  index: number,
  readings: readonly PageReading[],
): Finding[] {
  const cappedReading = readings.find((one) => one.id === idOf(index, "capped"));
  const wideReading = readings.find((one) => one.id === idOf(index, "wide"));
  if (cappedReading === undefined || wideReading === undefined) return [];

  /* ONE LINE BOX OF THIS TIER'S OWN, which the page reports: the label tier's is 13.8px and the compact tier's is
   * 9.5px, and taking the label figure for both reached four rows past the compact block's bottom rule. */
  const firstLine = Math.ceil(cappedReading.lineHeightPx);
  const cappedText = titleRegion(regionOf("capped", each), cappedReading, firstLine);
  const wideText = titleRegion(regionOf("wide", each), wideReading, firstLine);
  const textBox = Math.ceil(cappedReading.titleLeftPx + cappedReading.firstLineWidthPx);

  let reach = -1;
  for (let y = 0; y < firstLine; y += 1) {
    reach = Math.max(
      reach,
      lastInkedColumn(
        image,
        { ...cappedText, widthPx: Math.min(textBox, cappedText.widthPx) },
        y,
      ) ?? -1,
    );
  }
  if (reach < 0) return [];

  const differences = differencesBetween(image, cappedText, wideText, firstLine, reach + 1);
  if (differences.length === 0) return [];

  const total = differences.reduce((sum, row) => sum + row.differingPixels, 0);
  return [
    {
      file: SHEET,
      check: "rendered-title-prefix",
      message:
        `${each.name}: the first line of the capped title differs from the same title where nothing can ` +
        `truncate, in ${String(total)} pixel(s) over the ${String(reach + 1)} it draws. What a block shows has ` +
        "to be a PREFIX of the title, so a difference here is a truncation the RULE supplies rather than the " +
        `cap: an ellipsis from \`text-overflow\` truncates every copy alike and cancels out of the comparison ` +
        `above. Title: ${JSON.stringify(each.title)}.\n` +
        `        in the narrow column:\n${indent(sketch(image, cappedText, firstLine))}`,
    },
  ];
}

/** The rows one line of a block's title occupies, from where the page says its box begins. */
function titleRegion(block: Region, reading: PageReading, depthPx: number): Region {
  return { ...block, topPx: block.topPx + Math.round(reading.titleTopPx), heightPx: depthPx };
}

/* THE TITLE'S TOP OFFSET, which no screenshot can state and which is the figure the centring defect was found in. */
function topOffsetOf(each: CaseGeometry, index: number, readings: PageReading[]): Finding[] {
  const id = idOf(index, "capped");
  const reading = readings.find((one) => one.id === id);
  if (reading === undefined) {
    return [
      {
        file: SHEET,
        check: "rendered-geometry",
        message: `${each.name}: the page reported no geometry for ${id}, so nothing about its layout was measured.`,
      },
    ];
  }
  if (Math.abs(reading.titleTopPx - each.titleTopPx) <= OFFSET_TOLERANCE_PX) return [];

  return [
    {
      file: SHEET,
      check: "rendered-geometry",
      message:
        `${each.name}: the title's top edge sits ${reading.titleTopPx.toFixed(2)}px below the block's, and the ` +
        `${each.tier} tier's own arithmetic says ${String(each.titleTopPx)}px: the Area rule plus the padding ` +
        "that tier keeps. A calendar block's title is TOP-ALIGNED, and a button centres its content unless the " +
        "block is a column flex box with its content in one block child.",
    },
  ];
}

/* THE CHANNEL TABLE, MEASURED.
 *
 * Every rule the sheets state about how block states COMPOSE is asserted here over what a browser computed for one
 * of the state cases: the four border widths and colours each case's reading carries. The claims are relative
 * wherever an ink is involved -- conflict's winning colour is identified by equalling the conflict-only case's
 * reading and differing from selected-only's -- so retuning a pigment moves no assertion. The weights are the
 * composition rules' own figures, because those figures ARE the rules: 3px of state rule, 1px of split hairline,
 * 2px of Area top rule, and no right edge in any state at all.
 *
 * THE GATE'S OWN CONTROL IS THE PROPOSAL TARGET. The one historical defect this table exists to keep dead was a
 * `border` shorthand restored on `.week-block[data-proposal]`: it set all four edges, so the target lost the
 * Area's 2px top rule to a 1px dashed one and gained a right edge. Both halves are asserted on every case, so the
 * shorthand cannot come back on any state without reddening here.
 *
 * A MISSING READING IS A FINDING rather than a pass, for the same reason a blank region is: a gate that cannot see
 * must not report agreement. */
function channelTable(cases: readonly CaseGeometry[], readings: readonly PageReading[]): Finding[] {
  const findings: Finding[] = [];
  const readAt = (index: number): PageReading | undefined =>
    readings.find((one) => one.id === idOf(index, "capped"));
  for (const [index, each] of cases.entries()) {
    if (readAt(index) !== undefined) continue;
    findings.push({
      file: SHEET,
      check: "rendered-channel",
      message: `${each.name}: the page reported no composed reading, so none of its channels was measured.`,
    });
  }

  /* Two edges no state may move, on every case: there is no right border at any state, and the top rule stays the
   * Area's own weight even where the fill goes (a restored `border` shorthand sets both). */
  for (const [index, each] of cases.entries()) {
    const read = readAt(index);
    if (read === undefined) continue;
    if (read.borderRightWidth !== "0px") {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          `${each.name}: the block composes a ${read.borderRightWidth} RIGHT edge, and a block draws three edges, ` +
          "not four. Whatever set it took a channel nothing models: the left rule belongs to state, the top to the " +
          "Area, the bottom closes the block, and the right edge does not exist.",
      });
    }
    if (read.borderTopWidth !== `${String(AREA_RULE_PX)}px`) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          `${each.name}: the top rule composed at ${read.borderTopWidth}, not the Area's ` +
          `${String(AREA_RULE_PX)}px. A restored border shorthand on a state rule takes this edge first: identity ` +
          "is the top rule, and no state may re-weight it.",
      });
    }
  }

  /* CONFLICT WINS THE LEFT RULE OVER SELECTED, AT THE WEIGHT BOTH SHARE. */
  const conflict = soleCase(cases, { conflicted: true });
  const selected = soleCase(cases, { selected: true });
  const both = soleCase(cases, { conflicted: true, selected: true });
  const bothRead = both === -1 ? undefined : readAt(both);
  const conflictRead = conflict === -1 ? undefined : readAt(conflict);
  const selectedRead = selected === -1 ? undefined : readAt(selected);
  if (bothRead !== undefined && conflictRead !== undefined && selectedRead !== undefined) {
    if (bothRead.borderLeftWidth !== STATE_RULE_PX) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          `conflicted and selected: the left rule composed at ${bothRead.borderLeftWidth}, not the states' shared ` +
          `${STATE_RULE_PX}. Conflict wins the pixel while it lasts; it does not change its width to do it.`,
      });
    }
    if (bothRead.borderLeftColor !== conflictRead.borderLeftColor) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          "conflicted and selected: the left rule did not settle in conflict's ink. Conflict is declared second " +
          "so it wins while it lasts; selected out-ranking it here means the cascade order moved.",
      });
    }
    if (
      conflictRead.borderLeftColor === selectedRead.borderLeftColor ||
      conflictRead.borderLeftColor === TRANSPARENT
    ) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          "conflicted alone: the left rule's ink is indistinguishable from selected's, or from no ink at all. " +
          "The win above proves nothing unless the two states compose different inks.",
      });
    }
  }

  /* A SPLIT BLOCK'S OWN HAIRLINE IS REPLACED BY THE STATE RULE, NOT ADDED TO IT. */
  const splitRest = soleCase(cases, { split: true });
  const splitSelected = soleCase(cases, { split: true, selected: true });
  const splitRestRead = splitRest === -1 ? undefined : readAt(splitRest);
  const splitSelectedRead = splitSelected === -1 ? undefined : readAt(splitSelected);
  if (splitRestRead !== undefined) {
    if (
      splitRestRead.borderLeftWidth !== HAIRLINE_PX ||
      splitRestRead.borderLeftColor === TRANSPARENT
    ) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          "split at rest: the block drew no hairline left rule of its own, and with no left border of its own " +
          "nothing divides it from the block beside it.",
      });
    }
  }
  if (splitSelectedRead !== undefined && selectedRead !== undefined) {
    if (
      splitSelectedRead.borderLeftWidth !== STATE_RULE_PX ||
      splitSelectedRead.borderLeftColor !== selectedRead.borderLeftColor
    ) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          `split and selected: the left rule composed at ${splitSelectedRead.borderLeftWidth} in ` +
          `${splitSelectedRead.borderLeftColor}, not the state rule replacing the split's hairline at ` +
          `${STATE_RULE_PX} in selected's ink. Added rather than replaced shows up as a wider rule than either ` +
          "state alone draws.",
      });
    }
  }

  /* THE PROPOSAL TARGET: NO FILL, A DASHED BOTTOM RULE AS REDUNDANCY, AND EVERYTHING ELSE KEPT. */
  const proposal = soleCase(cases, { proposalTarget: true });
  const proposalRead = proposal === -1 ? undefined : readAt(proposal);
  const restRead = readAt(0);
  if (proposalRead !== undefined) {
    if (proposalRead.backgroundColor !== TRANSPARENT) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          `proposal target: the block composed a fill (${proposalRead.backgroundColor}), and absence of fill is ` +
          "the one thing that state owns.",
      });
    }
    if (proposalRead.borderBottomStyle !== "dashed") {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          `proposal target: the bottom rule composed ${proposalRead.borderBottomStyle}, not dashed. In forced ` +
          "colors the missing fill stops being visible, and the dashed redundancy is all that names the state.",
      });
    }
    if (restRead !== undefined && proposalRead.borderTopColor !== restRead.borderTopColor) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          "proposal target: the top rule's ink differs from the resting block's, and the state owns no channel " +
          "there. This is the exact loss the historical `border` shorthand caused: the Area's rule replaced by " +
          "the state's own edge.",
      });
    }
  }

  /* THE ANCHOR'S HATCH RIDES THE IMAGE CHANNEL, SO HOVER'S COLOUR COMPOSES WITH IT RATHER THAN COMPETING. */
  const anchorIndex = cases.findIndex((each) => each.origin === "anchor");
  const anchorRead = anchorIndex === -1 ? undefined : readAt(anchorIndex);
  if (anchorRead !== undefined && restRead !== undefined) {
    if (anchorRead.hatchBackgroundImage === null || anchorRead.hatchBackgroundImage === "none") {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          "anchor block: no hatch composed, so the external anchor reads as an assertion rather than as a " +
          "read-only fact. The hatch has to stay an image: a texture that owned the colour channel would be " +
          "erased the moment hover recoloured the fill.",
      });
    }
    if (anchorRead.backgroundColor === TRANSPARENT) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          "anchor block: the fill under the hatch is gone. Hover recolours THIS property, so an anchor with no " +
          "fill has nothing for hover to compose with.",
      });
    }
    if (anchorRead.borderTopColor === restRead.borderTopColor) {
      findings.push({
        file: SHEET,
        check: "rendered-channel",
        message:
          "anchor block: the top rule took the Area's pigment. An anchor has no Area, and its rule takes the " +
          "one ink that is not a step on the ramp.",
      });
    }
  }

  return findings;
}

/** The index of the one case standing in exactly these states, or -1 when no case carries them. */
function soleCase(cases: readonly CaseGeometry[], want: RenderCase["states"]): number {
  return cases.findIndex(
    (each) => JSON.stringify(each.states ?? {}) === JSON.stringify(want ?? {}),
  );
}

/* What the channel table concluded, for the run's notes: one line per state case, in its own words. */
function channelNotes(cases: readonly CaseGeometry[], readings: readonly PageReading[]): string[] {
  const lines: string[] = [];
  for (const [index, each] of cases.entries()) {
    if (Object.keys(each.states ?? {}).length === 0 && each.origin === undefined) continue;
    const read = readings.find((one) => one.id === idOf(index, "capped"));
    if (read === undefined) continue;
    lines.push(
      `  ${each.name}: left ${read.borderLeftWidth} ${read.borderLeftColor}, top ${read.borderTopWidth}, ` +
        `right ${read.borderRightWidth}, bottom ${read.borderBottomWidth} ${read.borderBottomStyle}`,
    );
  }
  return lines.length === 0 ? [] : ["composed channels:"].concat(lines);
}

/* THE DRAG'S RE-WEIGHTING, READ FROM THE LINES SECTION. Resting quarters differ from hours; dragged quarters equal them. */
function parseLineWeights(text: string): LineWeightReading | null {
  if (text.trim() === "") return null;
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null && "atRest" in parsed
      ? (parsed as LineWeightReading)
      : null;
  } catch {
    return null;
  }
}

function lineWeightFindings(weights: LineWeightReading | null): Finding[] {
  if (weights === null || weights.error !== undefined) {
    return [
      {
        file: path.join(frontendRoot, "scripts", "check-render", "lineWeight.ts"),
        check: "line-weight",
        message:
          "the page reported no line weighings, so whether data-dragging steps the quarter lines to hour weight " +
          "was never measured.",
      },
    ];
  }
  const findings: Finding[] = [];
  if (weights.atRest.quarter === weights.atRest.hour) {
    findings.push({
      file: path.join("frontend", "src", "ui", "domain", "week-grid", "grid.css"),
      check: "line-weight",
      message:
        "the quarter lines already sit at hour weight BEFORE any drag, so the step during one would show the " +
        "reader nothing: both states of the axis look alike.",
    });
  }
  if (weights.dragging.quarter !== weights.dragging.hour) {
    findings.push({
      file: path.join("frontend", "src", "ui", "domain", "week-grid", "grid.css"),
      check: "line-weight",
      message:
        "with data-dragging on the grid, the quarter lines still compose " +
        `${weights.dragging.quarter} against the hour lines' ${weights.dragging.hour}: the snap targets did not ` +
        "sharpen at the one moment the reader is aiming at them.",
    });
  }
  return findings;
}

function verdictNotes(report: ReturnType<typeof parseVerdictReport>): string[] {
  if (
    report === null ||
    report.error !== undefined ||
    report.panelBottomPx === undefined ||
    report.rows === undefined
  ) {
    return ["verdict panel: not measured"];
  }
  const fourth = report.rows.at(-1);
  if (fourth === undefined) return ["verdict panel: drew no rows"];
  return [
    `verdict panel: the clip sits at ${report.panelBottomPx.toFixed(2)}px and the fourth row spans ` +
      `${fourth.topPx.toFixed(2)}px to ${fourth.bottomPx.toFixed(2)}px`,
  ];
}

function parseReadings(text: string): PageReading[] {
  if (text.trim() === "") return [];
  try {
    const parsed: unknown = JSON.parse(text);
    return Array.isArray(parsed) ? (parsed as PageReading[]) : [];
  } catch {
    return [];
  }
}

function indent(lines: readonly string[]): string {
  return lines.map((line) => `          ${line}`).join("\n");
}
