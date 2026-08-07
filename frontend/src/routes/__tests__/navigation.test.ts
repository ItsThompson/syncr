/* NAVIGATION WITHOUT A RELOAD, ASSERTED OVER THE WHOLE APPLICATION RATHER THAN OVER ONE LAYER.
 *
 * A raw `<a href>` to a route this application owns reloads the document: it discards the SWR cache and re-runs the
 * gate and the bundle to reach a screen already in memory. `ui/domain`'s own layer test held this rule first, and its
 * SET WAS SMALLER THAN THE SET IT CLAIMED TO BOUND: it scanned `ui/domain` alone, so `routes/` and `app/` were a blind
 * spot, and the week screen's conflict banner shipped a raw anchor to `/templates` with the layer test green.
 *
 * TWO CLAIMS, BECAUSE ONE OF THEM CANNOT SEE EVERYTHING. A literal in-app path in the source is judgeable by reading
 * it. An href that arrives as a PROP or as DATA is not: a notice's action may point at an account page this product
 * does not serve, so `NoticePanel` and `NoticeStrip` are right to draw a raw anchor. So the second claim is an
 * inventory: the raw anchors in this application are exactly these two, and a third one has to be argued for here
 * rather than merely written. That is what catches the case a regex cannot.
 *
 * The reader is `testing/layerRules.ts`'s, which blanks comments first, so prose about an anchor cannot answer a
 * question about one. */

import path from "node:path";
import { describe, expect, it } from "vitest";

import { appSourceRoot } from "../../testing/kitSources";
import { layerSources } from "../../testing/layerRules";

/** Every tree that renders: the kit, the screens, and the shell above them. */
const TREES = ["ui", "routes", "app"] as const;

/** An `href` whose value is a literal path this application routes, rather than a prop that could lead anywhere. */
const LITERAL_IN_APP_HREF = /<a\s[^>]*href=\{?"\//;

/** Any raw anchor element at all, whatever its href is. */
const RAW_ANCHOR = /<a\s[^>]*href=/;

/**
 * The three components whose anchor is right, and why each one is.
 *
 * A notice's action arrives on the notice, composed by the api, and may lead outside this product entirely: a Google
 * re-authorisation is the case that shapes it. Neither notice component can know where it is sending a reader, so
 * neither may assume a route. The consent panel is the other direction of the same fact: the destination is Google's
 * own authorization URL, minted by the api, and leaving this application is the whole point of following it.
 */
const RAW_ANCHORS_BY_DESIGN = [
  "routes/settings/components/GoogleConsentPanel.tsx",
  "ui/domain/notices/NoticePanel.tsx",
  "ui/domain/notices/NoticeStrip.tsx",
];

/** One source file, named by the tree it sits in, so a finding names a path a reader can open. */
interface NamedSource {
  readonly name: string;
  readonly text: string;
}

async function sourcesInEveryTree(): Promise<NamedSource[]> {
  const trees = await Promise.all(
    TREES.map(async (tree) => {
      const sources = await layerSources(path.join(appSourceRoot, tree));
      const named: NamedSource[] = [];
      for (const file of sources) named.push({ name: `${tree}/${file.name}`, text: file.text });
      return named;
    }),
  );
  return trees.flat();
}

describe("the application navigates without reloading", () => {
  it("writes no raw anchor to a literal path of its own, in any tree", async () => {
    const sources = await sourcesInEveryTree();

    expect(
      sources.filter((file) => LITERAL_IN_APP_HREF.test(file.text)).map((f) => f.name),
    ).toEqual([]);
  });

  it("draws a raw anchor in exactly the three places whose destination is data", async () => {
    const sources = await sourcesInEveryTree();

    expect(
      sources
        .filter((file) => RAW_ANCHOR.test(file.text))
        .map((file) => file.name)
        .toSorted(),
    ).toEqual(RAW_ANCHORS_BY_DESIGN);
  });

  it("imports Link wherever it draws one, so a Link is react-router's and not a local component", async () => {
    const sources = await sourcesInEveryTree();
    const linking = sources.filter((file) => /<Link\b/.test(file.text));

    /* The set is not asserted exhaustively -- a screen may gain a link at any time -- but it must not be empty, or
     * this case would pass on an application that had stopped linking at all. */
    expect(linking.length).toBeGreaterThan(0);
    for (const file of linking) {
      expect(file.text, `${file.name} draws a Link without importing one`).toMatch(
        /import \{[^}]*\bLink\b[^}]*\} from "react-router"/,
      );
    }
  });
});
