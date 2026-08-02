#!/usr/bin/env node
/* The design rules that live in markup, and the ones derived from what a utility compiles to.
 * Runs in the pre-commit hook and in CI. */

import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, kitDir } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { lintMarkup } from "./lint.ts";

const outcome = await lintMarkup({
  sourceFiles: await filesUnder(appSourceDir, [".ts", ".tsx"]),
  // Every stylesheet under src except the token layer, which declares values rather than applying
  // utilities. `@apply` in any of them reaches the same emitted-CSS verdict a class name does.
  styleSheets: (await filesUnder(appSourceDir, [".css"])).filter(
    (file) => !file.startsWith(`${path.join(appSourceDir, "tokens")}${path.sep}`),
  ),
  themeFile: path.join(appSourceDir, "theme.css"),
  kitDir,
  sourceRoot: appSourceDir,
});

process.exit(reportOutcome("markup", outcome));
