/* THE CHECK: A CAPPED TITLE MUST RENDER THE SAME PIXELS AS AN UNCAPPED ONE OVER THE LINES IT SHOWS.
 *
 * That single comparison is both halves of the criterion at once. An END-ELLIPSIS is ink the uncapped rendering does
 * not have, so it fails. A MID-GLYPH CLIP is ink the uncapped rendering has more of, so it fails too. Neither can be
 * seen by reading `white-space`, `text-overflow` or any other declaration, which is how an ellipsis shipped: the
 * ellipsis arrives through `-webkit-line-clamp`, and the two properties the guard read cannot govern it.
 *
 * A MISSING BROWSER IS A FINDING. A check that passes when it cannot look reports a claim it never tested. */

import path from "node:path";

import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { BROWSER_ENV, findBrowser, screenshot } from "./browser.ts";
import { differencesBetween, imageOf, sketch, type Region } from "./pixels.ts";
import { CASES, COLUMN_PX, geometryOf, PAGE_PITCH_PX, probePage } from "./page.ts";

export interface CheckRenderInput {
  /** The built stylesheet a browser downloads, by name and content, from the same build the bundle gate reads. */
  readonly bundleName: string;
  readonly css: string;
}

/** How many rows of a sketch a finding carries, so the reader sees the line the difference lands in. */
const SKETCH_ROWS = 14;

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
  const bytes = await screenshot({
    browser,
    html: probePage({ bundleName, cases }),
    beside: { [bundleName]: css },
    widthPx: COLUMN_PX + 40,
    heightPx: cases.length * PAGE_PITCH_PX + 40,
  });
  const image = imageOf(bytes);

  const findings: Finding[] = [];
  for (const each of cases) {
    const capped: Region = {
      xPx: 0,
      widthPx: COLUMN_PX,
      topPx: each.cappedTopPx,
      heightPx: PAGE_PITCH_PX / 2,
    };
    const uncapped: Region = {
      xPx: 0,
      widthPx: COLUMN_PX,
      topPx: each.uncappedTopPx,
      heightPx: PAGE_PITCH_PX / 2,
    };
    const depthPx = Math.ceil(each.lines * 14);
    const differences = differencesBetween(image, capped, uncapped, depthPx);
    if (differences.length === 0) continue;

    const total = differences.reduce((sum, row) => sum + row.differingPixels, 0);
    findings.push({
      file: path.join("frontend", "src", "ui", "domain", "week-grid", "block.css"),
      check: "rendered-title",
      message:
        `${each.name}: the title capped at ${String(each.lines)} line(s) renders ${String(total)} pixel(s) ` +
        `differently from the same title uncapped, over the ${String(each.lines)} line(s) it shows. A cap adds ` +
        "nothing and removes nothing inside the lines it keeps, so a difference is an end-ellipsis or a clip " +
        `landing mid-glyph. Title: ${JSON.stringify(each.title)}.\n` +
        `        capped:\n${indent(sketch(image, capped, SKETCH_ROWS))}\n` +
        `        uncapped:\n${indent(sketch(image, uncapped, SKETCH_ROWS))}`,
    });
  }

  return {
    findings,
    notes: [
      `${path.basename(browser)}, ${bundleName}`,
      `${cases.length} case(s), each rendered capped and uncapped in a ${String(COLUMN_PX)}px column`,
      ...cases.map(
        (each) =>
          `  ${each.name}: ${each.durationMinutes}m at ${each.visibleHours}h is ` +
          `${each.heightPx.toFixed(3)}px, ${String(each.lines)} line(s)`,
      ),
    ],
  };
}

function indent(lines: readonly string[]): string {
  return lines.map((line) => `          ${line}`).join("\n");
}
