/* No file in the frontend identifies a routine by what it is called.
 *
 * A ROUTINE'S TITLE IS CONTENT, NOT AN IDENTIFIER. Two routines may legitimately carry the same one, a reader may
 * rename either at any time, and nothing on the wire promises that a particular title exists. A screen that reached
 * for one lost the tenant whose title was different and reached only the first of two that matched. Rendering a
 * title is how a row says which routine it is; comparing one is what this fence forbids.
 *
 * THE READING IS A SCAN OVER CODE, NOT OVER PROSE. Comments are blanked first, which is the convention
 * `barrelSideEffects.test.ts` and the markup rules follow: a rule sensitive enough to catch a title comparison is
 * sensitive enough to catch a sentence describing one, and a check that fails on its own documentation is a check
 * people route around. Offsets survive blanking, so a reported line is the real line.
 *
 * IT DOES NOT CARE WHAT THE RECEIVER IS CALLED. `title` compared, trimmed, lower-cased, matched or switched on is a
 * hit whether it was read from `routine`, from `r`, from `it` or destructured out of a parameter. Which of those a
 * reader would write is not knowable, and an earlier version of this fence keyed on the receiver being spelled
 * `routine`, which let `(r) => r.title === "Sleep"` through: the shape the deleted code would come back as.
 *
 * THREE TITLES IN THIS TREE ARE NOT ROUTINES' and they are excused by name below rather than by file, so a new
 * comparison has to be declared here even in a file that already holds one. What the scan cannot see is a title it
 * does not meet in one expression: one copied into a local first, including a routine copied into a variable this
 * list excuses; one reached through a helper; or one compared by a test matcher rather than by an operator. It
 * reads a line of code, not the flow into it. That is the bound, stated so nobody has to discover it. */

import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

import { blankJsComments } from "../../../../scripts/lib/comments.ts";
import { filesUnder } from "../../../../scripts/lib/files.ts";
import { frontendRoot, relativeToRepo } from "../../../../scripts/lib/paths.ts";

/* Every kind of file the frontend writes code in. `filesUnder` skips `node_modules`, `dist`, `coverage` and
   `__fixtures__`. */
const CODE = [".ts", ".tsx", ".mts"];

/* What turns reading a title into matching one. Two shapes: compared against a value, or normalized on the way to
   being compared. Not an exhaustive list of string operations, so a title formatted, sliced or rendered reaches
   none of them.

   A COMPARISON AGAINST `undefined` OR `null` IS NOT A MATCH and is excluded here rather than excused below: it
   asks whether a title is present, which cannot single out a routine. The kit's `Panel` asks exactly that of its
   own optional prop. */
const COMPARED_TO_A_VALUE = "(?:===|!==|==|!=)(?![=])(?!\\s*(?:undefined|null)\\b)";
const NORMALIZED =
  "(?:\\.trim|\\.toLowerCase|\\.toUpperCase|\\.localeCompare|\\.includes|\\.startsWith|\\.endsWith|\\.match\\b|\\.search\\b)";
const COMPARED = `(?:${COMPARED_TO_A_VALUE}|${NORMALIZED})`;

/* `x.title ===`, `title.toLowerCase()` destructured out of a parameter, and everything between. The lookbehind is
   what keeps `subtitle` out; the receiver is captured only so it can be checked against the list below. */
const TITLE_COMPARED = new RegExp(
  `(?:([A-Za-z_$][\\w$]*)\\s*\\.\\s*)?(?<![\\w$])title\\s*${COMPARED}`,
);

/* `switch (routine.title)`, whose cases are the comparison. */
const TITLE_SWITCHED = /switch\s*\([^)]*(?<![\w$])title\s*\)/;

/**
 * Receivers whose `title` is nobody's routine, excused by name with what they are.
 *
 * Excused by receiver rather than by path deliberately: a file that already holds one of these does not get a
 * blanket exemption, so a routine title compared in `draft.ts` still fails.
 */
const NOT_A_ROUTINE: Readonly<Record<string, string>> = {
  draft: "a captured task or habit being validated, whose title is a required non-empty string",
  candidate: "an unknown value being narrowed to a problem document",
};

interface Hit {
  readonly at: string;
  readonly receiver: string;
  readonly line: string;
}

async function titleReads(): Promise<{ readonly files: number; readonly hits: readonly Hit[] }> {
  const paths = await filesUnder(frontendRoot, CODE);
  const read = await Promise.all(
    paths.map(async (path) => ({ path, code: blankJsComments(await readFile(path, "utf8")) })),
  );

  const hits = read.flatMap((file) =>
    file.code.split("\n").reduce<Hit[]>((found, line, index) => {
      const compared = TITLE_COMPARED.exec(line);
      if (compared !== null)
        found.push({
          at: `${relativeToRepo(file.path)}:${index + 1}`,
          receiver: compared[1] ?? "",
          line: line.trim(),
        });
      else if (TITLE_SWITCHED.test(line))
        found.push({
          at: `${relativeToRepo(file.path)}:${index + 1}`,
          receiver: "",
          line: line.trim(),
        });
      return found;
    }, []),
  );

  return { files: read.length, hits };
}

describe("no file in the frontend matches a routine by title", () => {
  it("finds no comparison of a title the excused list does not account for", async () => {
    const { hits } = await titleReads();

    const guilty = hits.reduce<string[]>((found, hit) => {
      if (!(hit.receiver in NOT_A_ROUTINE)) found.push(`${hit.at}  ${hit.line}`);
      return found;
    }, []);

    expect(guilty).toEqual([]);
  });

  /* A scan that reads nothing reports clean, and a green result cannot tell that apart from a clean tree. So what
     it read is asserted too: the count is the frontend's own order of magnitude, not a threshold to tune. */
  it("read the tree it claims to have read", async () => {
    const { files, hits } = await titleReads();

    expect(files).toBeGreaterThan(200);
    expect(hits.length).toBeGreaterThan(0);
  });

  /* An excusal nothing uses is a hole nobody is paying for, and the next title comparison would fall into it
     silently. Each name has to still be doing the job it was excused for. */
  it("excuses no receiver the tree has stopped comparing", async () => {
    const { hits } = await titleReads();

    const excused = new Set(hits.map((hit) => hit.receiver));

    expect(Object.keys(NOT_A_ROUTINE).filter((name) => !excused.has(name))).toEqual([]);
  });
});
