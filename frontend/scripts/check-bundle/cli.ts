#!/usr/bin/env node
/* The built stylesheet, judged declaration by declaration. Runs in the pre-commit hook and in CI.
 *
 * This is the only check whose input is the artifact rather than the source, which is why it cannot
 * be folded into the markup scan: every extraction question the other checks have to answer is one
 * this check does not have to ask. */

import { buildStylesheets } from "./build.ts";
import { checkBundle } from "./check.ts";
import { reportOutcome } from "../lib/report.ts";

const stylesheets = await buildStylesheets();

if (stylesheets.length === 0) {
  process.stderr.write(
    "built bundle\n  the build produced no stylesheet, so this check examined nothing\n",
  );
  process.exit(1);
}

process.exit(reportOutcome("built bundle", checkBundle({ stylesheets })));
