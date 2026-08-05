#!/usr/bin/env node
/* `npm run lint:render`. The only check in this frontend whose input is a RENDERED PIXEL.
 *
 * Every other gate reads a declaration, a class list, an attribute or the built text, and each is blind to a
 * COMPOSED result. Three real defects on the week grid were compositions and each was caught by a person opening a
 * browser once: a `border` shorthand collapsing three edges into four, a proposal target losing the Area's top rule
 * to the same shorthand, and a `-webkit-line-clamp` shorthand supplying an end-ellipsis that reading `white-space`
 * and `text-overflow` could not see.
 *
 * NOT YET IN THE EIGHT-CHECK SET, and deliberately: no browser is a declared dependency of this repository, so
 * adding it to `just lint-frontend` and to CI is a change to what every agent's commit requires. That adoption is
 * ticket 1352's, along with the question of which browser CI gets. Run by hand until then. */

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
