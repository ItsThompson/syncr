/* THE TABLE'S COLUMN POLICY, MEASURED IN A REAL BROWSER OVER THE BUILT STYLESHEET.
 *
 * NOT A GATE, AND NOT IN THE SUITE. jsdom lays nothing out, so every claim about a WIDTH or a HEIGHT is
 * unfalsifiable in `vitest`: the committed suite holds the declarations and the markup, and this file exists to
 * settle what a browser does with them. It is run explicitly:
 *
 *   npx vite build
 *   npx vitest run --config probe/vitest.config.ts
 *
 * The suite's own include is `src/**` and `scripts/**`, so nothing here joins it by accident.
 *
 * WHAT IT SETTLES:
 *
 *   1. a cell wider than its column makes its own row taller,
 *   2. the columns beside it keep the widths they declared,
 *   3. and where a declared length is NOT exact: a table with no column claiming a share has nothing to absorb
 *      the difference, so a fixed layout scales every column, the reserved gutter included.
 *
 * The markup is the component's own, rendered with `renderToStaticMarkup`, so the page cannot drift from the
 * product the way a hand-written probe page can. The control is the same table with no column declaring anything,
 * which is what a table without a policy renders as: it is here to show the defect the policy fixes rather than to
 * be compared figure for figure.
 *
 * IT SPAWNS CHROME ITSELF RATHER THAN THROUGH `scripts/check-render/browser.ts`, for one reason: it gives Chrome a
 * `--user-data-dir` of its own, made fresh per run, so two runs can never contend for a profile and no wedged
 * browser can hold one open for the next. That costs one thing, stated at `dumpDom`: a Chrome given its own
 * profile does not exit after `--dump-dom`, so the dump itself is the signal to stop waiting. Where the browser IS
 * is the part worth sharing, and `findBrowser` is imported for it.
 *
 * THE PAGE, THE STYLESHEET AND THE READINGS ARE WRITTEN INTO THAT RUN DIRECTORY and its path is printed, so a
 * reader can open the exact document that was measured. Nothing is written inside the repository.
 *
 * The web font is not loaded offline, so a wrap lands on a different word than it does in production. Nothing here
 * turns on where the wrap lands: the claims are that a row grew, that its neighbours did not move, and that a
 * column is or is not the length it declared.
 */

import { spawn } from "node:child_process";
import { mkdtemp, readdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it } from "vitest";

import { BROWSER_ENV, findBrowser } from "../scripts/check-render/browser.ts";
import { Table, type TableColumn } from "../src/ui/domain/table/Table";

const PITCH_PX = 28;
const MARK_PX = 18;

/* What the table's own box loses to the row's state rule. `.state-row` draws a 3px transparent left border and
 * `border-collapse: collapse` puts half of a collapsed outer border inside the table, so every case here reads
 * 1.5px less across its columns than its container: it is systematic, it is the same in the undeclared control,
 * and the column that absorbs the surplus is the one that carries it. */
const ROW_RULE_PX = 1.5;

const NAME_AT_THE_CAP = "Weekday with lectures, a placement interview and a gym block";
const UNBREAKABLE_HEADER = "Unhyphenatedmultisyllabicheadingword";

interface Shape {
  readonly id: string;
  readonly name: string;
  readonly count: number;
}

const SHORT: readonly Shape[] = [
  { id: "1", name: "Weekday", count: 4 },
  { id: "2", name: "Saturday", count: 2 },
];

const LONG: readonly Shape[] = [
  { id: "1", name: NAME_AT_THE_CAP, count: 4 },
  { id: "2", name: "Saturday", count: 2 },
];

/** The day-shape list's own shape: the name column at the sidebar's width, the figure taking what is left. */
const NAME_AT_A_LENGTH: readonly TableColumn<Shape>[] = [
  { key: "name", header: "Shape", width: "236px", cell: (shape) => shape.name },
  {
    key: "count",
    header: "Entries",
    width: { weight: 1 },
    measure: "figure",
    cell: (shape) => shape.count,
  },
];

/** The other way round: the name absorbs the surplus and the figure column is the fixed one. */
const NAME_AT_A_WEIGHT: readonly TableColumn<Shape>[] = [
  { key: "name", header: "Shape", width: { weight: 1 }, cell: (shape) => shape.name },
  {
    key: "count",
    header: "Entries",
    width: "88px",
    measure: "figure",
    cell: (shape) => shape.count,
  },
];

/** What a table without a policy renders as: no column says anything, so the browser measures the content. */
const UNDECLARED: readonly TableColumn<Shape>[] = [
  { key: "name", header: "Shape", cell: (shape) => shape.name },
  { key: "count", header: "Entries", measure: "figure", cell: (shape) => shape.count },
];

/** EVERY column declares a length, so no column claims a share and nothing absorbs the difference. */
const EVERY_COLUMN_A_LENGTH: readonly TableColumn<Shape>[] = [
  { key: "name", header: "Shape", width: "236px", cell: (shape) => shape.name },
  {
    key: "count",
    header: "Entries",
    width: "88px",
    measure: "figure",
    cell: (shape) => shape.count,
  },
];

/** Lengths that already exceed the container, with nothing to absorb. */
const LENGTHS_OVER_THE_BOX: readonly TableColumn<Shape>[] = [
  { key: "name", header: "Shape", width: "500px", cell: (shape) => shape.name },
  {
    key: "count",
    header: "Entries",
    width: "200px",
    measure: "figure",
    cell: (shape) => shape.count,
  },
];

/** A weighted column whose surplus is negative, because the length beside it overshoots the container. */
const NEGATIVE_SURPLUS: readonly TableColumn<Shape>[] = [
  { key: "name", header: "Shape", width: "500px", cell: (shape) => shape.name },
  {
    key: "count",
    header: "Entries",
    width: { weight: 1 },
    measure: "figure",
    cell: (shape) => shape.count,
  },
];

/** A header word longer than its own narrow column, in a table whose headers are inert. */
const LONG_HEADER: readonly TableColumn<Shape>[] = [
  { key: "name", header: UNBREAKABLE_HEADER, width: "60px", cell: (shape) => shape.name },
  {
    key: "count",
    header: "Entries",
    width: { weight: 1 },
    measure: "figure",
    cell: (shape) => shape.count,
  },
];

/** The same header inside the sort button, which declares a height of its own. */
const LONG_HEADER_SORTABLE: readonly TableColumn<Shape>[] = LONG_HEADER.map((column) => ({
  ...column,
  isSortable: true,
}));

interface Case {
  readonly name: string;
  readonly columns: readonly TableColumn<Shape>[];
  readonly rows: readonly Shape[];
  readonly boxPx: number;
  readonly standing: boolean;
}

const CASES: readonly Case[] = [
  { name: "length-short", columns: NAME_AT_A_LENGTH, rows: SHORT, boxPx: 600, standing: false },
  { name: "length-long", columns: NAME_AT_A_LENGTH, rows: LONG, boxPx: 600, standing: false },
  {
    name: "length-long-standing",
    columns: NAME_AT_A_LENGTH,
    rows: LONG,
    boxPx: 600,
    standing: true,
  },
  { name: "weight-short", columns: NAME_AT_A_WEIGHT, rows: SHORT, boxPx: 300, standing: false },
  { name: "weight-long", columns: NAME_AT_A_WEIGHT, rows: LONG, boxPx: 300, standing: false },
  { name: "undeclared-short", columns: UNDECLARED, rows: SHORT, boxPx: 300, standing: false },
  { name: "undeclared-long", columns: UNDECLARED, rows: LONG, boxPx: 300, standing: false },
  {
    name: "all-lengths-short",
    columns: EVERY_COLUMN_A_LENGTH,
    rows: SHORT,
    boxPx: 600,
    standing: false,
  },
  {
    name: "all-lengths-long",
    columns: EVERY_COLUMN_A_LENGTH,
    rows: LONG,
    boxPx: 600,
    standing: false,
  },
  {
    name: "all-lengths-standing",
    columns: EVERY_COLUMN_A_LENGTH,
    rows: LONG,
    boxPx: 600,
    standing: true,
  },
  {
    name: "lengths-over-the-box",
    columns: LENGTHS_OVER_THE_BOX,
    rows: SHORT,
    boxPx: 300,
    standing: false,
  },
  { name: "negative-surplus", columns: NEGATIVE_SURPLUS, rows: SHORT, boxPx: 300, standing: false },
  { name: "long-header", columns: LONG_HEADER, rows: SHORT, boxPx: 300, standing: false },
  {
    name: "long-header-sortable",
    columns: LONG_HEADER_SORTABLE,
    rows: SHORT,
    boxPx: 300,
    standing: false,
  },
];

interface Reading {
  readonly name: string;
  readonly boxPx: number;
  readonly tablePx: number;
  readonly columnsPx: readonly number[];
  /** What each header cell's content measures, which exceeds its column when a word cannot break. */
  readonly headerScrollPx: readonly number[];
  readonly headerRowPx: number;
  readonly rowsPx: readonly number[];
}

function markup({ name, columns, rows, boxPx, standing }: Case): string {
  const table = renderToStaticMarkup(
    <Table
      caption="Day shapes"
      columns={columns}
      rows={rows}
      rowKey={(shape) => shape.id}
      onSortChange={() => undefined}
      {...(standing ? { standing: () => ({ isAtRisk: true }) } : {})}
    />,
  );
  return `<div class="case" data-case="${name}" style="width: ${String(boxPx)}px">${table}</div>`;
}

const PAGE_SCRIPT = `
  function round(value) { return Math.round(value * 100) / 100; }
  const readings = [...document.querySelectorAll(".case")].map((box) => ({
    name: box.dataset.case,
    boxPx: round(box.getBoundingClientRect().width),
    tablePx: round(box.querySelector("table").getBoundingClientRect().width),
    columnsPx: [...box.querySelectorAll("thead th")].map((cell) => round(cell.getBoundingClientRect().width)),
    headerScrollPx: [...box.querySelectorAll("thead th")].map((cell) => cell.scrollWidth),
    headerRowPx: round(box.querySelector("thead tr").getBoundingClientRect().height),
    rowsPx: [...box.querySelectorAll("tbody tr")].map((row) => round(row.getBoundingClientRect().height)),
  }));
  document.getElementById("readings").textContent = JSON.stringify(readings);
`;

async function bundleCss(): Promise<string> {
  const assets = path.resolve(import.meta.dirname, "..", "dist", "assets");
  const names = await readdir(assets);
  const sheet = names.find((name) => name.endsWith(".css"));
  if (sheet === undefined)
    throw new Error(`no built stylesheet in ${assets}: run \`npx vite build\``);
  return readFile(path.join(assets, sheet), "utf8");
}

/**
 * The page's DOM after it has settled, read from a Chrome that keeps a profile directory of its own.
 *
 * IT RESOLVES ON THE COMPLETED DUMP RATHER THAN ON THE PROCESS EXITING, because Chrome 151 does not exit after
 * `--dump-dom` when it is given an explicit `--user-data-dir`: it writes the whole document, then holds the profile
 * open indefinitely. Waiting for the exit is what wedges a run. The dump ends at `</html>`, so that is the signal,
 * and the browser is killed once it has said everything it was asked for.
 */
function dumpDom(browser: string, run: string, page: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      browser,
      [
        "--headless=new",
        `--user-data-dir=${path.join(run, "chrome-profile")}`,
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=1440,2400",
        "--virtual-time-budget=3000",
        "--dump-dom",
        `file://${page}`,
      ],
      { stdio: ["ignore", "pipe", "ignore"] },
    );
    let out = "";
    child.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString();
      if (out.includes("</html>")) {
        child.kill();
        resolve(out);
      }
    });
    child.on("error", reject);
    child.on("exit", () => {
      resolve(out);
    });
  });
}

async function measure(): Promise<Reading[]> {
  const browser = await findBrowser();
  if (browser === null) {
    throw new Error(`no Chrome or Chromium found. Point ${BROWSER_ENV} at one`);
  }

  const page = [
    "<!doctype html>",
    '<html lang="en"><head><meta charset="utf-8">',
    '<link rel="stylesheet" href="bundle.css"></head><body>',
    ...CASES.map(markup),
    '<pre id="readings"></pre>',
    `<script>${PAGE_SCRIPT}</script>`,
    "</body></html>",
  ].join("\n");

  const run = await mkdtemp(path.join(tmpdir(), "syncr-table-probe-"));
  process.stdout.write(`the page, the stylesheet and the readings are in ${run}\n`);
  await writeFile(path.join(run, "bundle.css"), await bundleCss(), "utf8");
  await writeFile(path.join(run, "page.html"), page, "utf8");

  const dom = await dumpDom(browser, run, path.join(run, "page.html"));
  const found = /<pre id="readings">([\s\S]*?)<\/pre>/.exec(dom);
  if (found === null) throw new Error("the page reported no readings");
  const readings = JSON.parse(
    found[1].replaceAll("&quot;", '"').replaceAll("&amp;", "&"),
  ) as Reading[];
  await writeFile(path.join(run, "readings.json"), JSON.stringify(readings, null, 2), "utf8");
  return readings;
}

const sum = (values: readonly number[]): number => values.reduce((total, each) => total + each, 0);

describe("the column policy in a browser", () => {
  let readings: readonly Reading[] = [];

  /* One page, one browser, one reading, whatever asserts against it: the cases are independent claims about the
   * same rendered document. */
  beforeAll(async () => {
    readings = await measure();
    process.stdout.write(`${JSON.stringify(readings, null, 2)}\n`);
  });

  const by = (name: string): Reading => {
    const found = readings.find((reading) => reading.name === name);
    if (found === undefined) throw new Error(`no reading for ${name}`);
    return found;
  };

  it("grows the row a long cell is in and holds every declared column still", () => {
    const lengthShort = by("length-short");
    const lengthLong = by("length-long");
    const standing = by("length-long-standing");
    const weightShort = by("weight-short");
    const weightLong = by("weight-long");
    const looseShort = by("undeclared-short");
    const looseLong = by("undeclared-long");

    // 1. The row the long cell is in grows; its neighbour stays at the pitch, and so do both rows of the same
    //    table with a short name in it.
    expect(lengthLong.rowsPx[0]).toBeGreaterThan(PITCH_PX);
    expect(lengthLong.rowsPx[1]).toBe(PITCH_PX);
    expect(lengthShort.rowsPx).toEqual([PITCH_PX, PITCH_PX]);
    expect(weightLong.rowsPx[0]).toBeGreaterThan(PITCH_PX);
    expect(weightLong.rowsPx[1]).toBe(PITCH_PX);

    // 2. Every column keeps the width it declared, whichever column the long cell is in.
    expect(lengthLong.columnsPx).toEqual(lengthShort.columnsPx);
    expect(lengthLong.columnsPx).toEqual([236, lengthLong.boxPx - 236 - ROW_RULE_PX]);
    expect(weightLong.columnsPx).toEqual(weightShort.columnsPx);
    expect(weightLong.columnsPx).toEqual([weightLong.boxPx - 88 - ROW_RULE_PX, 88]);

    // The reserved standing column comes out of the surplus rather than out of the container.
    expect(standing.tablePx).toBe(standing.boxPx);
    expect(standing.columnsPx).toEqual([
      MARK_PX,
      236,
      standing.boxPx - 236 - MARK_PX - ROW_RULE_PX,
    ]);
    expect(standing.rowsPx[0]).toBeGreaterThan(PITCH_PX);

    // The control: with nothing declared, the same long cell moves the column beside it.
    expect(looseLong.columnsPx).not.toEqual(looseShort.columnsPx);
  });

  /* WHERE A DECLARED LENGTH IS NOT EXACT, which is the qualification `table.css` and `columnWidths.ts` carry. A
   * length is subtracted and the shares divide what is left, so with no share claimed nothing absorbs the
   * difference between the lengths and the table, and a fixed layout scales all of them. */
  it("scales every column of a table that claims no share, because nothing absorbs the difference", () => {
    const short = by("all-lengths-short");
    const long = by("all-lengths-long");
    const standing = by("all-lengths-standing");
    const overTheBox = by("lengths-over-the-box");
    const negative = by("negative-surplus");

    // The rows still move nothing: what the policy fixes is fixed here too.
    expect(long.columnsPx).toEqual(short.columnsPx);
    expect(long.rowsPx[0]).toBeGreaterThan(PITCH_PX);
    expect(long.rowsPx[1]).toBe(PITCH_PX);

    // What they do not do is take the lengths they declared. Both are scaled, in the ratio of the declarations.
    expect(short.columnsPx).not.toEqual([236, 88]);
    expect(sum(short.columnsPx)).toBeCloseTo(short.boxPx - ROW_RULE_PX, 1);
    expect(short.columnsPx[0] / short.columnsPx[1]).toBeCloseTo(236 / 88, 2);

    // The reserved gutter is scaled with them: 18px is exact only where a column absorbs.
    expect(standing.columnsPx[0]).toBeGreaterThan(MARK_PX);

    // Lengths adding up past the container overflow it rather than shrinking to fit.
    expect(overTheBox.columnsPx).toEqual([500, 200]);
    expect(overTheBox.tablePx).toBeGreaterThan(overTheBox.boxPx);

    // A share beside such lengths resolves to nothing at all.
    expect(negative.columnsPx[1]).toBe(0);
  });

  /* A `<th>` IS A CELL. Without `overflow-wrap` on `.table__header` an unbroken header word measured 267px of
   * content inside a 60px column, drawn over the column beside it, with its own row still at the pitch.
   *
   * The sortable case breaks inside its column too, and its ROW is the one thing this file cannot claim grows:
   * `.table__sort` declares a height rather than a minimum, so the wrapped text is clipped instead. The figure is
   * in the readings; the rule belongs to whoever takes that button. */
  it("breaks an unbreakable header word inside its own column, ordered by or not", () => {
    const inert = by("long-header");
    const sortable = by("long-header-sortable");

    expect(inert.headerScrollPx[0]).toBeLessThanOrEqual(inert.columnsPx[0]);
    expect(inert.headerRowPx).toBeGreaterThan(PITCH_PX);
    expect(sortable.headerScrollPx[0]).toBeLessThanOrEqual(sortable.columnsPx[0]);
  });
});
