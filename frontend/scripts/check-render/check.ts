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
 * A MISSING BROWSER IS A FINDING. A check that passes when it cannot look reports a claim it never tested. */

import path from "node:path";

import { LINE_HEIGHT_PX } from "../../src/ui/domain/week-grid/metrics.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { BROWSER_ENV, findBrowser, screenshot } from "./browser.ts";
import { differencesBetween, imageOf, lastInkedColumn, sketch, type Region } from "./pixels.ts";
import {
  CASES,
  COLUMN_PX,
  geometryOf,
  idOf,
  PAGE_PITCH_PX,
  pageHeightPx,
  probePage,
  WIDE_COLUMN_PX,
  type CaseGeometry,
  type PageReading,
} from "./page.ts";

export interface CheckRenderInput {
  /** The built stylesheet a browser downloads, by name and content, from the build the bundle gate reads. */
  readonly bundleName: string;
  readonly css: string;
}

/** How many rows of a sketch a finding carries, so the reader sees the line the difference lands in. */
const SKETCH_ROWS = 14;

/** How far a measured offset may sit from the arithmetic before it is a finding. Sub-pixel rounding, nothing more. */
const OFFSET_TOLERANCE_PX = 0.5;

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
  const shot = await screenshot({
    browser,
    html: probePage({ bundleName, cases }),
    beside: { [bundleName]: css },
    widthPx: WIDE_COLUMN_PX + 40,
    heightPx: pageHeightPx(cases),
  });
  const image = imageOf(shot.png);
  const readings = parseReadings(shot.readings);

  const findings: Finding[] = [];
  for (const [index, each] of cases.entries()) {
    findings.push(...cappedAgainstUncapped(image, each));
    findings.push(...cappedAgainstUntruncatable(image, each, index, readings));
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
    ],
  };
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
