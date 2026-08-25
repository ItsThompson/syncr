#!/usr/bin/env node
/* `npm run lint:render`. The only check in this frontend whose input is a RENDERED PIXEL.
 *
 * Every other gate reads a declaration, a class list, an attribute or the built text, and each is blind to a
 * COMPOSED result. Three real defects on the week grid were compositions and each was caught by a person opening a
 * browser once: a `border` shorthand collapsing three edges into four, a proposal target losing the Area's top rule
 * to the same shorthand, and a `-webkit-line-clamp` shorthand supplying an end-ellipsis that reading `white-space`
 * and `text-overflow` could not see.
 *
 * THE LAST CHECK `just lint-frontend` RUNS, in the pre-commit hook and in CI. No browser is a declared
 * dependency of this repository, so it uses the one already installed and REFUSES rather than skips when it finds
 * none: a check that passes when it cannot look reports a claim it never tested. GitHub's ubuntu runner images ship
 * `/usr/bin/google-chrome`, which is one of the paths it probes, so CI needs no setup step.
 *
 * Its title cases are the nine the clamp needed, and the page also lays out the week's seven day columns, which is
 * where the drag's horizontal read is measured against a box a browser computed rather than one a test stubbed. */

import { buildStylesheets } from "../check-bundle/build.ts";
import { checkRender } from "./check.ts";
import { reportOutcome } from "../lib/report.ts";

const stylesheets = await buildStylesheets();
const bundle = stylesheets.find((sheet) => sheet.name.endsWith(".css"));

if (bundle === undefined) {
  process.stderr.write(
    "rendered pixels\n  the build produced no stylesheet, so nothing was rendered and nothing measured\n",
  );
  process.exit(1);
}

process.exit(
  reportOutcome("rendered pixels", await checkRender({ bundleName: bundle.name, css: bundle.css })),
);
