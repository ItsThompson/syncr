#!/usr/bin/env node
/* `just tokens-validate`. Also runs in the pre-commit hook and in CI. */

import { readdir, stat } from "node:fs/promises";
import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, designSheetDir, tokenDir, tokenEntry } from "../lib/paths.ts";
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
 * every co-located component sheet wherever it sits. Scoped to the whole source tree rather than to
 * the kit, because a dangling reference in `src/routes/WeekRoute.css` is the same silent failure as
 * one in `src/ui/`, and a check that only looks where stylesheets happen to live today stops
 * covering the tree the moment one moves. */
const consumerFiles = (await filesUnder(appSourceDir, [".css"])).filter(
  (file) => !file.startsWith(`${tokenDir}${path.sep}`),
);

/* Every module and stylesheet the application ships, which is the graph a consumer's references are resolved
 * against: what a browser has loaded when it reads a component's sheet is whatever the module that imported that
 * sheet pulled in with it. Tests are excluded, because a test's imports are not a shipped cascade. */
const moduleFiles = (await filesUnder(appSourceDir, [".ts", ".tsx", ".css"])).filter(
  (file) => !file.includes(".test."),
);

const outcome = await validateTokenLayer({
  tokenFiles: await filesWithExtension(tokenDir, ".css"),
  consumerFiles,
  moduleFiles,
  exists: async (candidate) => {
    try {
      return (await stat(candidate)).isFile();
    } catch {
      return false;
    }
  },
  tokenEntry,
  sheetFiles: await filesWithExtension(designSheetDir, ".html"),
});

process.exit(reportOutcome("token layer", outcome));
