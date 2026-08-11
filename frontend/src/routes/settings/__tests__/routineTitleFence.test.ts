/* No file in the frontend identifies a routine by what it is called.
 *
 * A ROUTINE'S TITLE IS CONTENT, NOT AN IDENTIFIER. Two routines may legitimately carry the same one, a reader may
 * rename either at any time, and nothing on the wire promises that a particular title exists. A screen that reached
 * for one lost the tenant whose title was different and reached only the first of two that matched. Rendering a
 * title is how a row says which routine it is; comparing one is what this fence forbids.
 *
 * THE READING IS A SCAN, WHICH BOUNDS WHAT IT CAN PROVE. It sees a title read straight off a routine and then
 * compared, lower-cased, trimmed or matched, which is the shape the deleted code had and the shape anyone reaching
 * for the old behaviour would write again. It does not see a title copied into a local and compared a line later, so
 * it is a fence against the return of a pattern rather than a proof of its impossibility. */

import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

import { filesUnder } from "../../../../scripts/lib/files.ts";
import { frontendRoot, relativeToRepo } from "../../../../scripts/lib/paths.ts";

/* Every kind of file the frontend writes code in. `filesUnder` skips `node_modules`, `dist` and `coverage`. */
const CODE = [".ts", ".tsx", ".mts"];

/* A title read from anything routine-shaped, followed by a comparison or a match. The alternation is the set of
   operators a title match is written with; a title handed to a label, a cell or a request reaches none of them. */
const MATCHED_BY_TITLE =
  /routines?(?:\[[^\]]*\])?\.title\s*(?:={2,3}|!={1,2}|\.trim|\.toLowerCase|\.toUpperCase|\.includes|\.startsWith|\.endsWith|\.match|\.search|\.localeCompare)/;

async function scanned(): Promise<readonly { readonly path: string; readonly text: string }[]> {
  const paths = await filesUnder(frontendRoot, CODE);
  return Promise.all(paths.map(async (path) => ({ path, text: await readFile(path, "utf8") })));
}

describe("no file in the frontend matches a routine by title", () => {
  it("finds no comparison of a routine's title anywhere under frontend/", async () => {
    const files = await scanned();

    const guilty = files.flatMap((file) =>
      file.text.split("\n").reduce<string[]>((found, line, index) => {
        if (MATCHED_BY_TITLE.test(line)) found.push(`${relativeToRepo(file.path)}:${index + 1}`);
        return found;
      }, []),
    );

    expect(guilty).toEqual([]);
  });

  /* A scan that reads nothing reports clean, and a green result cannot tell that apart from a clean tree. So what
     it read is asserted too: the count is the frontend's own order of magnitude, not a threshold to tune. */
  it("read the tree it claims to have read", async () => {
    const files = await scanned();

    expect(files.length).toBeGreaterThan(200);
    expect(files.some((file) => file.path.endsWith("routineFloor.ts"))).toBe(true);
  });
});
