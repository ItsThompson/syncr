#!/usr/bin/env node
/* `just tokens-validate`. Also runs in the pre-commit hook and in CI. */

import { readdir } from "node:fs/promises";
import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, designSheetDir, kitDir, tokenDir, tokenEntry } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { validateTokenLayer } from "./validate.ts";

async function filesWithExtension(root: string, extension: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true, recursive: true });
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(extension))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .toSorted();
}

/* Every stylesheet that reads the layer without being part of it: the theme, the base rules, and
 * each co-located component sheet. A dangling reference in any of them is the same silent failure
 * as one inside the layer. */
const consumerFiles = [
  path.join(appSourceDir, "theme.css"),
  path.join(appSourceDir, "base.css"),
  ...(await filesUnder(kitDir, [".css"])),
];

const outcome = await validateTokenLayer({
  tokenFiles: await filesWithExtension(tokenDir, ".css"),
  consumerFiles,
  tokenEntry,
  sheetFiles: await filesWithExtension(designSheetDir, ".html"),
});

process.exit(reportOutcome("token layer", outcome));
