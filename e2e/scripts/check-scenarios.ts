#!/usr/bin/env node
/* The status table in `docs/smoke-scenarios.md` and the suite must agree, and this is what checks it.
 *
 * A LIST IS A SECOND COPY OF A FACT. The table's job is to be the map from section 22's done-criteria
 * table to something that can fail, and it has been wrong twice. Round 1: the S17 row claimed an
 * assertion no file in the suite made. Round 2: three rows named a spec file the same round had deleted,
 * because the first version of THIS FILE read the scenario and the status columns and stopped, which
 * left the column a reader follows to find the assertion unchecked. The set it could see was not the set
 * it claimed to bound.
 *
 * So it now reads every column it is meant to bound, in both directions:
 *
 *   every scenario the table marks automated has a test that names its number
 *   every scenario a test names is marked automated or partly automated
 *   every `*.spec.ts` the Where column names EXISTS
 *   for an automated row, the file the Where column names is a file that holds a test naming it
 *
 * THE TITLES COME FROM PLAYWRIGHT, NOT FROM A REGEX OVER THE SOURCE. The first version matched
 * `test("S...` textually, which counted a COMMENTED-OUT case as coverage: the exact defect this file
 * exists to catch, re-admitted through the back door. `--list` reports the tests that would run, so a
 * commented-out case is invisible and a `test.skip` or `test.only` is reported as what it is. It runs no
 * test and needs no stack.
 */

import { execFile } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

const here: string = import.meta.dirname;
const e2eDir = path.join(here, "..");
const testsDir = path.join(e2eDir, "tests");
const tableFile = path.join(e2eDir, "..", "docs", "smoke-scenarios.md");

/* A row of the 37-scenario table: `| S12 | what it observes | status | where |`. The observation cell is
 * matched non-greedily across pipes so a code span or a union type in it does not shift the columns; the
 * status is the third cell and the rest of the line is the Where column. */
const ROW = /^\|\s*(S\d{1,2})\s*\|(.*)\|([^|]*)\|([^|]*)\|\s*$/;

/* A spec file named in the Where column, inside a backtick span. */
const NAMED_SPEC = /`([\w.-]+\.spec\.ts)`/g;

const NUMBER = /\bS\d{1,2}\b/g;

const AUTOMATED = "automated";
const PARTLY = "partly automated";

type Row = { readonly status: string; readonly where: string; readonly line: number };

const asStatus = (cell: string): string => {
  const stated = cell.replaceAll("*", "").trim().toLowerCase();
  if (stated.startsWith(PARTLY)) return PARTLY;
  if (stated.startsWith(AUTOMATED)) return AUTOMATED;
  return stated;
};

const isCovered = (status: string): boolean => status === AUTOMATED || status === PARTLY;

const tableRows = async (): Promise<Map<string, Row>> => {
  const rows = new Map<string, Row>();
  const lines = (await readFile(tableFile, "utf8")).split("\n");
  for (const [index, line] of lines.entries()) {
    const match = ROW.exec(line);
    if (!match) continue;
    // The observation cell may itself hold pipes, so the STATUS is the second-to-last cell and the
    // Where column is the last. Recover them from the end rather than from a fixed offset.
    const cells = line
      .replace(/^\|/, "")
      .replace(/\|\s*$/, "")
      .split("|");
    rows.set(match[1]!, {
      status: asStatus(cells.at(-2) ?? ""),
      where: cells.at(-1) ?? "",
      line: index + 1,
    });
  }
  return rows;
};

type Listed = { readonly title: string; readonly file: string };

type PlaywrightSuite = {
  readonly file?: string;
  readonly specs?: readonly { readonly title?: string; readonly file?: string }[];
  readonly suites?: readonly PlaywrightSuite[];
};

const flatten = (suite: PlaywrightSuite): readonly Listed[] => [
  ...(suite.specs ?? []).map((spec) => ({
    title: spec.title ?? "",
    file: spec.file ?? suite.file ?? "",
  })),
  ...(suite.suites ?? []).flatMap(flatten),
];

/** Every test Playwright would run, as a title and the file it lives in. */
const listedTests = async (): Promise<readonly Listed[]> => {
  const { stdout } = await run("npx", ["playwright", "test", "--list", "--reporter=json"], {
    cwd: e2eDir,
    maxBuffer: 16 * 1024 * 1024,
  });
  const report = JSON.parse(stdout) as { readonly suites?: readonly PlaywrightSuite[] };
  return (report.suites ?? []).flatMap(flatten);
};

const exists = async (file: string): Promise<boolean> => {
  try {
    await access(path.join(testsDir, file));
    return true;
  } catch {
    return false;
  }
};

const rows = await tableRows();
const listed = await listedTests();

/* Which files hold a test naming each scenario. */
const namedBy = new Map<string, Set<string>>();
for (const test of listed) {
  for (const number of test.title.matchAll(NUMBER)) {
    const files = namedBy.get(number[0]) ?? new Set<string>();
    files.add(test.file);
    namedBy.set(number[0], files);
  }
}

const problems: string[] = [];

if (rows.size !== 37) {
  problems.push(`the table lists ${rows.size} scenarios; section 20 numbers 37`);
}

for (const [scenario, row] of rows) {
  const files = namedBy.get(scenario);
  if (isCovered(row.status) && !files) {
    problems.push(
      `line ${row.line}: the table marks ${scenario} "${row.status}" and no test names it`,
    );
  }

  // Every spec file the Where column names must exist, whatever the row's status. This is the column
  // three rows of it went stale in when a file was split in two.
  const named = [...row.where.matchAll(NAMED_SPEC)].map((match) => match[1]!);
  for (const file of named) {
    if (!(await exists(file))) {
      problems.push(
        `line ${row.line}: ${scenario} names ${file}, which does not exist under tests/`,
      );
    }
  }

  // And for a covered row, at least one file it names must be a file that holds a test naming it.
  if (isCovered(row.status) && files && named.length > 0) {
    if (!named.some((file) => files.has(file))) {
      problems.push(
        `line ${row.line}: ${scenario} names ${named.join(", ")} and its tests live in ` +
          `${[...files].join(", ")}`,
      );
    }
  }
  if (isCovered(row.status) && named.length === 0) {
    problems.push(
      `line ${row.line}: ${scenario} is "${row.status}" and its row names no spec file`,
    );
  }
}

for (const [scenario, files] of namedBy) {
  const row = rows.get(scenario);
  if (row === undefined) {
    problems.push(`${[...files].join(", ")} names ${scenario} and the table has no row for it`);
  } else if (!isCovered(row.status)) {
    problems.push(
      `line ${row.line}: ${[...files].join(", ")} names ${scenario} and the table calls it ` +
        `"${row.status}" rather than automated`,
    );
  }
}

if (problems.length > 0) {
  console.error("the scenario table and the suite disagree:");
  for (const problem of problems) console.error(`  ${problem}`);
  process.exit(1);
}

console.log(
  `scenario table: ok, ${rows.size} rows, ${namedBy.size} scenarios named by ${listed.length} tests`,
);
