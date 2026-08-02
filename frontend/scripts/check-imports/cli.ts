#!/usr/bin/env node
/* The kit's import zones, checked against the resolved module graph rather than against a table of
 * specifier spellings. Runs in the pre-commit hook and in CI. */

import { stat } from "node:fs/promises";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, kitDir } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { checkImports } from "./check.ts";

/* Tests are excluded: a test legitimately reaches for a hook or a route to exercise it. The zone
 * rule is about what SHIPS, and oxlint's own overrides make the same exclusion. */
const kitFiles = (await filesUnder(kitDir, [".ts", ".tsx"])).filter(
  (file) => !file.includes(".test."),
);

const outcome = await checkImports({
  kitFiles,
  sourceRoot: appSourceDir,
  exists: async (candidate) => {
    try {
      return (await stat(candidate)).isFile();
    } catch {
      return false;
    }
  },
});

process.exit(reportOutcome("kit imports", outcome));
