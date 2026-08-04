/* The commitments in a span, and the type each one matched.
 *
 * READ-ONLY, EVERY ONE OF THEM. syncr never edits or deletes an imported commitment, so this hook has no
 * write beside it. What the anchor types tab needs from an anchor is which type it holds and where that
 * type came from, because a rule match and a retype are two different facts and a reader editing rules
 * has to be able to tell them apart.
 *
 * THE PAGE'S END IS CARRIED RATHER THAN HIDDEN. The route is keyset-paginated, so a span busy enough to
 * fill a page has more behind it. Handing back `nextCursor` lets the table say that instead of showing
 * the first two hundred as if they were all of them. This hook reads one page: following the cursor is a
 * second concern, and no surface here needs it yet. */

import useSWR from "swr";

import { client } from "../client";
import { anchorsKey } from "../keys";
import { read } from "./request";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Anchor = components["schemas"]["AnchorResponse"];

export interface AnchorPage {
  readonly anchors: readonly Anchor[];
  /** Non-null when the span holds more commitments than this page carries. */
  readonly nextCursor: string | null;
}

async function readAnchors(from: string, to: string): Promise<AnchorPage> {
  const page = await read(() => client.GET("/api/v1/anchors", { params: { query: { from, to } } }));
  return { anchors: page.anchors, nextCursor: page.nextCursor ?? null };
}

/** One page of the commitments between two instants, both carrying an offset. */
export function useAnchors(from: string, to: string): Resource<AnchorPage> {
  return toResource(useSWR<AnchorPage, Problem>(anchorsKey(from, to), () => readAnchors(from, to)));
}
