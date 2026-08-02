#!/usr/bin/env node
/* The design rules that live in markup. Runs in the pre-commit hook and in CI. */

import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, kitDir } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { lintMarkup } from "./lint.ts";

const outcome = await lintMarkup({
  sourceFiles: await filesUnder(appSourceDir, [".ts", ".tsx"]),
  themeFile: path.join(appSourceDir, "theme.css"),
  kitDir,
});

process.exit(reportOutcome("markup", outcome));
