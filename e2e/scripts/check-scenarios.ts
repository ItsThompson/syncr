#!/usr/bin/env node
/* The status table in `docs/smoke-scenarios.md` and the suite must agree, and this is what checks it.
 *
 * A LIST IS A SECOND COPY OF A FACT. The table's job is to be the map from a scenario number to the
 * assertion that covers it, and a check that reads only the scenario and the status columns leaves the
 * column a reader follows to find that assertion unchecked: the set it can see is then not the set it
 * claims to bound. Two kinds of staleness got through that way, a row claiming an assertion no file in
 * the suite made and rows naming a spec file that no longer existed.
 *
 * So it now reads every column it is meant to bound, in both directions:
 *
 *   every scenario the table marks automated has a test that names its number
 *   every scenario a test names is marked automated or partly automated
 *   every `*.spec.ts` the Where column names EXISTS
 *   for an automated row, the file the Where column names is a file that holds a test naming it
 *   every repository path and every `just` recipe the Where column names RESOLVES
 *
 * THAT LAST ONE IS THE COLUMN'S OTHER TWO THIRDS. Two python test paths and thirteen recipe names live in
 * the Where column, and a measurement showed a nonexistent path and a nonexistent recipe both leaving this
 * check at exit 0. All fifteen resolve, so nothing was wrong; what was wrong was the bound. Three
 * widenings of this same guard have now been needed, which is the argument for checking rather than
 * proofreading.
 *
 * WHAT IS STILL NOT BOUNDED, stated so the next reader does not have to measure it: the OBSERVATION cell is
 * prose and nothing here reads it. Three of the table's four columns are asserted.
 *
 * THE TITLES COME FROM PLAYWRIGHT, NOT FROM A REGEX OVER THE SOURCE. The first version matched
 * `test("S...` textually, which counted a COMMENTED-OUT case as coverage: the exact defect this file
 * exists to catch, re-admitted through the back door. `--list` reports the tests that would run, so a
 * commented-out case is invisible and a `test.skip` or `test.only` is reported as what it is. It runs no
 * test and needs no stack. That reading lives in `suite.ts`, because `check-spec-scenarios.ts` crosses a
 * second statement against the same listing and two readings of it would be two things to keep in step.
 */

import { execFile } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import { listedTests, scenariosNamed } from "./suite.ts";

const run = promisify(execFile);

const here: string = import.meta.dirname;
const e2eDir = path.join(here, "..");
const testsDir = path.join(e2eDir, "tests");
const repoRoot = path.join(e2eDir, "..");
const tableFile = path.join(repoRoot, "docs", "smoke-scenarios.md");

/* A row of the 37-scenario table. A SHAPE GUARD rather than an extractor: the cells are split out below,
 * because the observation cell may itself contain a pipe and a fixed capture group would shift the columns
 * when it does. */
const ROW = /^\|\s*(S\d{1,2})\s*\|.*\|.*\|.*\|\s*$/;

/* A spec file named in the Where column, inside a backtick span. */
const NAMED_SPEC = /`([\w.-]+\.spec\.ts)`/g;

/* A repository path named in the Where column: a backtick span holding a slash and no space. Catches
 * `packages/syncr-api/tests/test_approval_during_a_solve.py`, which the S30 row names. */
const NAMED_PATH = /`([\w./-]*\/[\w./-]+)`/g;

/* A `just` recipe named in the Where column. */
const NAMED_RECIPE = /`just ([\w-]+)`/g;

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

const exists = async (file: string): Promise<boolean> => {
  try {
    await access(path.join(testsDir, file));
    return true;
  } catch {
    return false;
  }
};

const existsFromRoot = async (relative: string): Promise<boolean> => {
  try {
    await access(path.join(repoRoot, relative));
    return true;
  } catch {
    return false;
  }
};

/** Every recipe name `just` knows about, so a cited one can be resolved rather than read. */
const knownRecipes = async (): Promise<ReadonlySet<string>> => {
  const { stdout } = await run("just", ["--summary"], { cwd: repoRoot });
  return new Set(stdout.split(/\s+/).filter(Boolean));
};

const rows = await tableRows();
const listed = await listedTests();
const recipes = await knownRecipes();

/* Which files hold a test naming each scenario. */
const namedBy = new Map<string, Set<string>>();
for (const test of listed) {
  for (const number of scenariosNamed(test.title)) {
    const files = namedBy.get(number) ?? new Set<string>();
    files.add(test.file);
    namedBy.set(number, files);
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

  // The Where column's other two thirds: a repository path and a `just` recipe are both citations a reader
  // follows, and neither was checked until a measurement showed a fake one passing.
  for (const cited of [...row.where.matchAll(NAMED_PATH)].map((match) => match[1]!)) {
    if (cited.endsWith(".spec.ts")) continue;
    if (!(await existsFromRoot(cited))) {
      problems.push(`line ${row.line}: ${scenario} cites ${cited}, which does not exist`);
    }
  }
  for (const cited of [...row.where.matchAll(NAMED_RECIPE)].map((match) => match[1]!)) {
    if (!recipes.has(cited)) {
      problems.push(`line ${row.line}: ${scenario} cites \`just ${cited}\`, which is not a recipe`);
    }
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
