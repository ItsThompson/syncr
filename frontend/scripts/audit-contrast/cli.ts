#!/usr/bin/env node
/* `npm run lint:contrast`. Also runs in the pre-commit hook and in CI.
 *
 * With `--write` it writes the ledger; without one it regenerates it in memory and refuses a difference, which is
 * how the committed document stays the one the tokens produce. */

import { writeFile } from "node:fs/promises";
import path from "node:path";

import { designSheetDir } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { buildLedger } from "./ledger.ts";
import { renderLedger } from "./render.ts";
import { checkContrast } from "./check.ts";

/** Beside the six reference sheets, which is where a reviewer already looks for a measured figure. */
const LEDGER_FILE = path.join(designSheetDir, "contrast-ledger.md");

const ledger = await buildLedger();

if (process.argv.includes("--write")) {
  await writeFile(LEDGER_FILE, renderLedger(ledger), "utf8");
  process.stdout.write(`contrast ledger\n  wrote ${LEDGER_FILE}\n`);
}

process.exit(
  reportOutcome("contrast ledger", await checkContrast({ ledger, ledgerFile: LEDGER_FILE })),
);
