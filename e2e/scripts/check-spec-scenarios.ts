#!/usr/bin/env node
/* `scenarios.md` states which numbered scenario each spec drives, and this is what checks it.
 *
 * WHY A SECOND STATEMENT EXISTS. `docs/smoke-scenarios.md` is keyed on the SCENARIO: it maps each of the 37 to
 * the file that drives it, which is the direction a reader follows from a done-criteria table. Two things it
 * structurally cannot say. It cannot account for a spec file that drives none of the 37, because it has no row
 * to hang one on. And it cannot notice a NEW spec file at all, because nothing in it is keyed on the set of
 * files. `scenarios.md` is keyed on the file, so every `*.spec.ts` in `tests/` is accounted for or the gate
 * goes red.
 *
 * A LIST IS A SECOND COPY OF A FACT, so this one is crossed against the suite rather than proofread, in both
 * directions and on every column it claims to bound. Five things fail here:
 *
 *   every `*.spec.ts` under `tests/` has exactly one row
 *   every row names a file that exists under `tests/`
 *   every one of those files holds at least one case Playwright would run
 *   the numbers a row states are exactly the numbers that file's case titles name
 *   a scenario cell is `none` or a comma-separated list of scenario numbers, and nothing else
 *
 * WHAT IS NOT BOUNDED, stated so the next reader does not have to measure it: the third column is prose and
 * nothing here reads it. Two of the three columns are asserted.
 *
 * THE TITLES COME FROM PLAYWRIGHT rather than from a regex over the source, through `suite.ts`, which is the
 * reading `check-scenarios.ts` uses for the same reason: a regex counts a commented-out case as coverage.
 */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { listedTests, scenariosNamed } from "./suite.ts";

const e2eDir = path.join(import.meta.dirname, "..");
const testsDir = path.join(e2eDir, "tests");
const statementFile = path.join(e2eDir, "scenarios.md");

/* A row of the statement: a backticked spec file, then the cell that says which scenarios it drives. The
 * third cell is prose and may hold anything, including a pipe, so it is not captured. */
const ROW = /^\|\s*`([\w./-]+\.spec\.ts)`\s*\|([^|]*)\|/;

/** What a row says when the file it names drives none of the numbered scenarios. */
const NONE = "none";

const A_NUMBER = /^S\d{1,2}$/;

type Stated = { readonly scenarios: readonly string[]; readonly line: number };

const problems: string[] = [];

/** Every row of the statement, keyed on the file it names. */
const statedRows = async (): Promise<ReadonlyMap<string, Stated>> => {
  const rows = new Map<string, Stated>();
  const lines = (await readFile(statementFile, "utf8")).split("\n");
  for (const [index, line] of lines.entries()) {
    const match = ROW.exec(line);
    if (!match) continue;
    const file = match[1]!;
    const at = index + 1;
    const cell = match[2]!.trim();

    const already = rows.get(file);
    if (already !== undefined) {
      problems.push(`line ${at}: ${file} already has a row, at line ${already.line}`);
      continue;
    }

    const scenarios = cell.toLowerCase() === NONE ? [] : cell.split(",").map((part) => part.trim());
    const unreadable = scenarios.filter((part) => !A_NUMBER.test(part));
    if (unreadable.length > 0) {
      problems.push(
        `line ${at}: ${file} states "${cell}", and ${unreadable.join(", ")} is not a scenario ` +
          `number. A row states \`${NONE}\` or a comma-separated list of them`,
      );
      continue;
    }
    rows.set(file, { scenarios, line: at });
  }
  return rows;
};

/** Every spec file under `tests/`, as Playwright would name it. */
const specFiles = async (): Promise<readonly string[]> =>
  (await readdir(testsDir, { recursive: true }))
    .filter((name) => name.endsWith(".spec.ts"))
    .map((name) => name.split(path.sep).join("/"))
    .toSorted();

const stated = await statedRows();
const onDisk = await specFiles();
const listed = await listedTests();

/** Which scenario numbers each file's cases name, and which files hold a case at all. */
const named = new Map<string, Set<string>>();
for (const test of listed) {
  const numbers = named.get(test.file) ?? new Set<string>();
  for (const number of scenariosNamed(test.title)) numbers.add(number);
  named.set(test.file, numbers);
}

for (const file of onDisk) {
  const row = stated.get(file);
  if (row === undefined) {
    problems.push(`tests/${file} has no row in scenarios.md, so nothing states what it drives`);
    continue;
  }
  const numbers = named.get(file);
  if (numbers === undefined) {
    problems.push(
      `line ${row.line}: playwright would run no case in tests/${file}, so its row bounds nothing`,
    );
    continue;
  }
  const drives = [...numbers].toSorted();
  const claims = [...row.scenarios].toSorted();
  if (drives.join(", ") !== claims.join(", ")) {
    problems.push(
      `line ${row.line}: ${file} states ${claims.length === 0 ? NONE : claims.join(", ")} and its ` +
        `cases name ${drives.length === 0 ? NONE : drives.join(", ")}`,
    );
  }
}

for (const [file, row] of stated) {
  if (!onDisk.includes(file)) {
    problems.push(`line ${row.line}: ${file} does not exist under tests/`);
  }
}

if (problems.length > 0) {
  console.error("scenarios.md and the suite disagree:");
  for (const problem of problems) console.error(`  ${problem}`);
  process.exit(1);
}

const drivenCount = new Set([...named.values()].flatMap((numbers) => [...numbers])).size;
console.log(
  `spec statement: ok, ${onDisk.length} specs stated, ${drivenCount} scenarios driven by ` +
    `${listed.length} tests`,
);
