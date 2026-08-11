#!/usr/bin/env node
/* Every test Playwright would run, and the scenario numbers a title names.
 *
 * HERE RATHER THAN IN EITHER GATE, because both of them cross a statement against the suite and neither owns
 * the reading. A second reading would be a regex over the source, which is the defect this one exists to
 * prevent: `--list` reports the tests that WOULD run, so a commented-out case is invisible to it and a
 * `test.skip` or `test.only` is reported as what it is.
 */

import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

const e2eDir = path.join(import.meta.dirname, "..");

/** A scenario number, as a test title names it. */
const NUMBER = /\bS\d{1,2}\b/g;

/** One test, and the file it lives in, relative to the suite's `testDir`. */
export type Listed = { readonly title: string; readonly file: string };

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
export const listedTests = async (): Promise<readonly Listed[]> => {
  const { stdout } = await run("npx", ["playwright", "test", "--list", "--reporter=json"], {
    cwd: e2eDir,
    maxBuffer: 16 * 1024 * 1024,
  });
  const report = JSON.parse(stdout) as { readonly suites?: readonly PlaywrightSuite[] };
  return (report.suites ?? []).flatMap(flatten);
};

/** The scenario numbers a title names, in the order it names them. */
export const scenariosNamed = (title: string): readonly string[] =>
  [...title.matchAll(NUMBER)].map((match) => match[0]);

/** Whether a token is a scenario number, by the same grammar `scenariosNamed` reads titles with. */
export const isScenarioNumber = (token: string): boolean =>
  new RegExp(`^${NUMBER.source}$`).test(token);
