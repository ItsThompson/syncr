#!/usr/bin/env node
/* Each state channel is assigned in exactly one file under the kit. Runs in CI. */

import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, kitDir } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { checkChannels } from "./check.ts";
import { checkUnsafeClientCalls } from "./unsafe-client-calls-check.ts";

/* Tests are excluded: a test asserting a state is not the kit assigning a channel. */
const kitFiles = (await filesUnder(kitDir, [".css", ".tsx"])).filter(
  (file) => !file.includes(".test."),
);

const channelOutcome = await checkChannels({
  kitFiles,
  themeFile: path.join(appSourceDir, "theme.css"),
});
const hookFiles = (
  await filesUnder(path.join(appSourceDir, "api", "hooks"), [".ts", ".tsx"])
).filter((file) => !file.includes(".test."));
const unsafeCallOutcome = await checkUnsafeClientCalls({ hookFiles });

process.exit(
  reportOutcome("state channels and unsafe client calls", {
    findings: [...channelOutcome.findings, ...unsafeCallOutcome.findings],
    notes: [...channelOutcome.notes, ...unsafeCallOutcome.notes],
  }),
);
