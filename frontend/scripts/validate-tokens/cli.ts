#!/usr/bin/env node
/* `just tokens-validate`. Also runs in the pre-commit hook and in CI. */

import { readdir } from "node:fs/promises";
import path from "node:path";

import { designSheetDir, tokenDir, tokenEntry } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { validateTokenLayer } from "./validate.ts";

async function filesWithExtension(root: string, extension: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true, recursive: true });
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(extension))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .toSorted();
}

const outcome = await validateTokenLayer({
  tokenFiles: await filesWithExtension(tokenDir, ".css"),
  tokenEntry,
  sheetFiles: await filesWithExtension(designSheetDir, ".html"),
});

process.exit(reportOutcome("token layer", outcome));
