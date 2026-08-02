#!/usr/bin/env node
/* Each state channel is assigned in exactly one file under the kit. Runs in CI. */

import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, kitDir } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { checkChannels } from "./check.ts";

/* Tests are excluded: a test asserting a state is not the kit assigning a channel. */
const kitFiles = (await filesUnder(kitDir, [".css", ".tsx"])).filter(
  (file) => !file.includes(".test."),
);

const outcome = await checkChannels({
  kitFiles,
  themeFile: path.join(appSourceDir, "theme.css"),
});

process.exit(reportOutcome("state channels", outcome));
