#!/usr/bin/env node
/* The status table in `docs/smoke-scenarios.md` and the suite must agree, and this is what checks it.
 *
 * A LIST IS A SECOND COPY OF A FACT. The table's job is to be the map from section 22's done-criteria
 * table to something that can fail, and its first version claimed S17's `no_eligible_content` reason was
 * asserted in `s01` when no file in the suite mentioned it. A reader of that row was told a scenario was
 * covered when nothing in the suite had ever produced an unfillable slot.
 *
 * So the two facts are crossed rather than trusted:
 *
 *   every scenario the table marks `automated` has a test title naming its number
 *   every scenario a test title names is marked `automated` or `partly automated` in the table
 *
 * It reads the test titles out of the spec files by pattern rather than by running Playwright, so it is a
 * static check that costs nothing and needs no stack.
 */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const here = import.meta.dirname;
const testsDir = path.join(here, "..", "tests");
const tableFile = path.join(here, "..", "..", "docs", "smoke-scenarios.md");

/* A row of the 37-scenario table: `| S12 | what it observes | status | where |`. */
const ROW = /^\|\s*(S\d{1,2})\s*\|[^|]*\|\s*([^|]*?)\s*\|/;

/* A test's title, whichever quote it uses and however many lines it spans. Every scenario number the
 * title names counts: one case can be the observation for two scenarios, and the acceptance criterion is
 * that the number appears in the title rather than at the start of it. */
const TITLE = /test\(\s*(["'`])((?:\\.|(?!\1)[\s\S])*)\1/g;
const NUMBER = /\bS\d{1,2}\b/g;

const AUTOMATED = "automated";
const PARTLY = "partly automated";

const asStatus = (cell) => {
  const stated = cell.replaceAll("*", "").trim().toLowerCase();
  if (stated.startsWith(PARTLY)) return PARTLY;
  if (stated.startsWith(AUTOMATED)) return AUTOMATED;
  return stated;
};

const tableStatuses = async () => {
  const statuses = new Map();
  for (const line of (await readFile(tableFile, "utf8")).split("\n")) {
    const match = ROW.exec(line);
    if (match) statuses.set(match[1], asStatus(match[2]));
  }
  return statuses;
};

const suiteScenarios = async () => {
  const found = new Map();
  for (const entry of await readdir(testsDir)) {
    if (!entry.endsWith(".spec.ts")) continue;
    const source = await readFile(path.join(testsDir, entry), "utf8");
    for (const title of source.matchAll(TITLE)) {
      for (const number of (title[2] ?? "").matchAll(NUMBER)) {
        found.set(number[0], [...new Set([...(found.get(number[0]) ?? []), entry])]);
      }
    }
  }
  return found;
};

const statuses = await tableStatuses();
const suite = await suiteScenarios();
const problems = [];

if (statuses.size !== 37) {
  problems.push(`the table lists ${statuses.size} scenarios; section 20 numbers 37`);
}

for (const [scenario, status] of statuses) {
  if (status !== AUTOMATED && status !== PARTLY) continue;
  if (!suite.has(scenario)) {
    problems.push(`the table marks ${scenario} "${status}" and no test title names it`);
  }
}

for (const [scenario, files] of suite) {
  const status = statuses.get(scenario);
  if (status === undefined) {
    problems.push(`${files.join(", ")} names ${scenario} and the table has no row for it`);
  } else if (status !== AUTOMATED && status !== PARTLY) {
    problems.push(
      `${files.join(", ")} names ${scenario} and the table calls it "${status}" rather than automated`,
    );
  }
}

if (problems.length > 0) {
  console.error("the scenario table and the suite disagree:");
  for (const problem of problems) console.error(`  ${problem}`);
  process.exit(1);
}

console.log(
  `scenario table: ok, ${statuses.size} rows, ${suite.size} scenarios named by a test title`,
);
